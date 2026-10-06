from __future__ import annotations

import base64
import asyncio
import hashlib
import hmac
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Mapping, Protocol, Sequence
from urllib.parse import urlencode, urlsplit

import httpx

from app.core.config import settings


logger = logging.getLogger("uvicorn.error")
# httpx logs full request URLs at INFO. Maintenance URLs can contain signed
# media tokens, and provider configuration values must never enter logs.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)


RINGCENTRAL_SMS_EVENT_FILTER = (
    "/restapi/v1.0/account/~/extension/~/message-store/instant?type=SMS"
)


def twilio_signature(url: str, params: Mapping[str, str], auth_token: str) -> str:
    value = url + "".join(f"{key}{params[key]}" for key in sorted(params))
    digest = hmac.new(auth_token.encode(), value.encode(), hashlib.sha1).digest()
    return base64.b64encode(digest).decode()


def validate_twilio_signature(
    url: str, params: Mapping[str, str], supplied: str, auth_token: str
) -> bool:
    return bool(supplied) and hmac.compare_digest(twilio_signature(url, params, auth_token), supplied)


class SmsProvider(Protocol):
    async def send(self, to: str, body: str, media_urls: Sequence[str]) -> str: ...
    def validate_signature(self, url: str, params: Mapping[str, str], signature: str) -> bool: ...
    async def fetch_media(self, url: str) -> bytes: ...


class StagingSmsRecipientBlocked(RuntimeError):
    """Raised at the provider boundary before a staging SMS can leave Office Hub."""


def enforce_staging_sms_recipient(to: str) -> None:
    if not settings.is_staging:
        return
    if to in settings.staging_sms_allowlist_values:
        return
    logger.warning("Dropped staging SMS to non-allowlisted phone ending %s", to[-4:])
    raise StagingSmsRecipientBlocked("Staging SMS recipient is not allowlisted")


@dataclass
class FakeProvider:
    auth_token: str = "test-auth-token"
    sent: list[dict[str, object]] = field(default_factory=list)
    media: dict[str, bytes] = field(default_factory=dict)

    async def send(self, to: str, body: str, media_urls: Sequence[str]) -> str:
        enforce_staging_sms_recipient(to)
        sid = f"SMFAKE{len(self.sent) + 1:08d}"
        self.sent.append({"sid": sid, "to": to, "body": body, "media_urls": list(media_urls)})
        logger.info("Fake SMS queued to phone ending %s", to[-4:])
        return sid

    def validate_signature(self, url: str, params: Mapping[str, str], signature: str) -> bool:
        return validate_twilio_signature(url, params, signature, self.auth_token)

    async def fetch_media(self, url: str) -> bytes:
        if url not in self.media:
            raise ValueError("Fake media URL was not registered")
        return self.media[url]


class TwilioProvider:
    def __init__(self, account_sid: str, auth_token: str, from_number: str) -> None:
        self.account_sid = account_sid
        self.auth_token = auth_token
        self.from_number = from_number

    async def send(self, to: str, body: str, media_urls: Sequence[str]) -> str:
        enforce_staging_sms_recipient(to)
        url = f"https://api.twilio.com/2010-04-01/Accounts/{self.account_sid}/Messages.json"
        form: list[tuple[str, str]] = [("To", to), ("From", self.from_number), ("Body", body)]
        form.extend(("MediaUrl", media_url) for media_url in media_urls)
        if settings.maintenance_enabled:
            form.append(("StatusCallback", f"{settings.public_base_url.rstrip('/')}/api/webhooks/twilio/status"))
        async with httpx.AsyncClient(timeout=15, auth=(self.account_sid, self.auth_token)) as client:
            response = await client.post(
                url,
                content=urlencode(form),
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            response.raise_for_status()
            return str(response.json()["sid"])

    def validate_signature(self, url: str, params: Mapping[str, str], signature: str) -> bool:
        return validate_twilio_signature(url, params, signature, self.auth_token)

    async def fetch_media(self, url: str) -> bytes:
        async with httpx.AsyncClient(timeout=20, auth=(self.account_sid, self.auth_token)) as client:
            response = await client.get(url)
            response.raise_for_status()
            return response.content


class RingCentralProvider:
    """RingCentral JWT provider with an in-memory OAuth access-token cache."""

    def __init__(
        self,
        server_url: str,
        client_id: str,
        client_secret: str,
        jwt: str,
        from_number: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.server_url = server_url.rstrip("/")
        self.client_id = client_id
        self.client_secret = client_secret
        self.jwt = jwt
        self.from_number = from_number
        self.transport = transport
        self._access_token = ""
        self._access_token_expires_at = 0.0
        self._token_lock = asyncio.Lock()

    async def _bearer_token(self) -> str:
        if self._access_token and time.monotonic() < self._access_token_expires_at:
            return self._access_token
        async with self._token_lock:
            if self._access_token and time.monotonic() < self._access_token_expires_at:
                return self._access_token
            async with httpx.AsyncClient(
                timeout=15,
                auth=(self.client_id, self.client_secret),
                transport=self.transport,
            ) as client:
                response = await client.post(
                    f"{self.server_url}/restapi/oauth/token",
                    data={
                        "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                        "assertion": self.jwt,
                    },
                    headers={"Accept": "application/json"},
                )
                response.raise_for_status()
                payload = response.json()
            self._access_token = str(payload["access_token"])
            expires_in = max(int(payload.get("expires_in", 3600)), 120)
            self._access_token_expires_at = time.monotonic() + expires_in - 60
            return self._access_token

    async def authenticate(self) -> None:
        """Validate the configured JWT grant without exposing the access token."""
        await self._bearer_token()

    async def send(self, to: str, body: str, media_urls: Sequence[str]) -> str:
        enforce_staging_sms_recipient(to)
        token = await self._bearer_token()
        payload = {
            "from": {"phoneNumber": self.from_number},
            "to": [{"phoneNumber": to}],
            "text": body,
        }
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        async with httpx.AsyncClient(timeout=30, transport=self.transport) as client:
            if media_urls:
                files: list[tuple[str, tuple[str | None, bytes | str, str]]] = [
                    ("json", (None, json.dumps(payload), "application/json"))
                ]
                for index, media_url in enumerate(media_urls):
                    media = await client.get(media_url)
                    media.raise_for_status()
                    content_type = media.headers.get("Content-Type", "application/octet-stream").split(";", 1)[0]
                    files.append(
                        ("attachment", (f"attachment-{index + 1}", media.content, content_type))
                    )
                response = await client.post(
                    f"{self.server_url}/restapi/v1.0/account/~/extension/~/mms",
                    headers=headers,
                    files=files,
                )
            else:
                response = await client.post(
                    f"{self.server_url}/restapi/v1.0/account/~/extension/~/sms",
                    headers=headers,
                    json=payload,
                )
            response.raise_for_status()
            return str(response.json()["id"])

    async def create_sms_webhook_subscription(
        self,
        address: str,
        validation_token: str,
        *,
        expires_in: int = 604799,
    ) -> Mapping[str, object]:
        """Create an inbound-SMS webhook subscription after explicit ops invocation."""
        token = await self._bearer_token()
        async with httpx.AsyncClient(timeout=30, transport=self.transport) as client:
            response = await client.post(
                f"{self.server_url}/restapi/v1.0/subscription",
                headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
                json={
                    "eventFilters": [RINGCENTRAL_SMS_EVENT_FILTER],
                    "deliveryMode": {
                        "transportType": "WebHook",
                        "address": address,
                        "validationToken": validation_token,
                    },
                    "expiresIn": expires_in,
                },
            )
            response.raise_for_status()
            payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("RingCentral returned an invalid subscription response")
        return payload

    def validate_signature(self, url: str, params: Mapping[str, str], signature: str) -> bool:
        # RingCentral notifications use subscription validation tokens, not the
        # Twilio form-signature scheme handled by this interface.
        return False

    async def fetch_media(self, url: str) -> bytes:
        expected = urlsplit(self.server_url)
        supplied = urlsplit(url)
        if (
            supplied.scheme != expected.scheme
            or supplied.netloc != expected.netloc
            or not supplied.path.startswith("/restapi/")
        ):
            raise ValueError("RingCentral media URL is outside the configured API origin")
        token = await self._bearer_token()
        async with httpx.AsyncClient(timeout=20, transport=self.transport) as client:
            response = await client.get(url, headers={"Authorization": f"Bearer {token}"})
            response.raise_for_status()
            return response.content


_provider: SmsProvider | None = None


def get_sms_provider() -> SmsProvider:
    global _provider
    if _provider is not None:
        return _provider
    provider_name = settings.sms_provider.casefold()
    if provider_name == "ringcentral":
        if settings.ringcentral_configured:
            _provider = RingCentralProvider(
                settings.ringcentral_server_url,
                settings.ringcentral_client_id,
                settings.ringcentral_client_secret.get_secret_value(),
                settings.ringcentral_jwt.get_secret_value(),
                settings.ringcentral_from_number,
            )
        elif settings.environment.casefold() not in {"development", "test", "testing"}:
            raise RuntimeError("RingCentral is selected but is not fully configured")
        else:
            logger.warning("RingCentral is unconfigured; using FakeProvider in %s", settings.environment)
            _provider = FakeProvider()
    elif provider_name == "twilio":
        if settings.twilio_configured:
            _provider = TwilioProvider(
                settings.twilio_account_sid,
                settings.twilio_auth_token,
                settings.twilio_from_number,
            )
        elif settings.environment.casefold() not in {"development", "test", "testing"}:
            raise RuntimeError("Twilio is selected but its credentials/from number are not configured")
        else:
            logger.warning("Twilio is unconfigured; using FakeProvider in %s", settings.environment)
            _provider = FakeProvider(settings.twilio_auth_token or "test-auth-token")
    elif provider_name == "fake" or settings.environment.casefold() in {"development", "test", "testing"}:
        _provider = FakeProvider(settings.twilio_auth_token or "test-auth-token")
    else:
        raise RuntimeError("Unsupported SMS_PROVIDER")
    return _provider


def set_sms_provider(provider: SmsProvider | None) -> None:
    global _provider
    _provider = provider
