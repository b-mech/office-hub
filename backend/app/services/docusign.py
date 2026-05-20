from __future__ import annotations

import base64
import logging
import time
from dataclasses import dataclass
from typing import Any

import httpx
from jose import jwt

from app.core.config import settings


logger = logging.getLogger(__name__)


class DocuSignConfigurationError(RuntimeError):
    pass


class DocuSignEnvelopeError(RuntimeError):
    pass


@dataclass(frozen=True)
class DocuSignEnvelopeResult:
    envelope_id: str
    status: str


def configured() -> bool:
    return settings.docusign_configured


async def send_change_order_envelope(
    pdf_bytes: bytes,
    filename: str,
    email_subject: str,
    signer_name: str,
    signer_email: str,
) -> DocuSignEnvelopeResult:
    if not configured():
        raise DocuSignConfigurationError("DocuSign is not configured.")

    token = await _access_token()
    document_base64 = base64.b64encode(pdf_bytes).decode("ascii")
    payload: dict[str, Any] = {
        "emailSubject": email_subject,
        "documents": [
            {
                "documentBase64": document_base64,
                "name": filename,
                "fileExtension": "pdf",
                "documentId": "1",
            }
        ],
        "recipients": {
            "signers": [
                {
                    "email": signer_email,
                    "name": signer_name,
                    "recipientId": "1",
                    "routingOrder": "1",
                    "tabs": {
                        "signHereTabs": [
                            {
                                "anchorString": "Purchaser Signature",
                                "anchorUnits": "pixels",
                                "anchorXOffset": "0",
                                "anchorYOffset": "-32",
                            }
                        ],
                        "dateSignedTabs": [
                            {
                                "anchorString": "Date",
                                "anchorUnits": "pixels",
                                "anchorXOffset": "0",
                                "anchorYOffset": "-32",
                            }
                        ],
                    },
                }
            ]
        },
        "status": "sent",
    }
    url = f"{settings.docusign_base_path.rstrip('/')}/v2.1/accounts/{settings.docusign_account_id}/envelopes"
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(url, headers=_auth_headers(token), json=payload)

    if response.status_code >= 400:
        logger.warning("DocuSign envelope creation failed: %s %s", response.status_code, response.text)
        raise DocuSignEnvelopeError(_error_detail(response))

    data = response.json()
    return DocuSignEnvelopeResult(
        envelope_id=str(data.get("envelopeId", "")),
        status=str(data.get("status", "sent")),
    )


async def get_envelope_status(envelope_id: str) -> str:
    if not configured():
        raise DocuSignConfigurationError("DocuSign is not configured.")

    token = await _access_token()
    url = (
        f"{settings.docusign_base_path.rstrip('/')}/v2.1/accounts/"
        f"{settings.docusign_account_id}/envelopes/{envelope_id}"
    )
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(url, headers=_auth_headers(token))

    if response.status_code >= 400:
        logger.warning("DocuSign envelope status failed: %s %s", response.status_code, response.text)
        raise DocuSignEnvelopeError(_error_detail(response))
    return str(response.json().get("status", "unknown"))


async def download_completed_document(envelope_id: str) -> bytes | None:
    status = await get_envelope_status(envelope_id)
    if status.lower() != "completed":
        return None

    token = await _access_token()
    url = (
        f"{settings.docusign_base_path.rstrip('/')}/v2.1/accounts/"
        f"{settings.docusign_account_id}/envelopes/{envelope_id}/documents/combined"
    )
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(url, headers=_auth_headers(token))

    if response.status_code >= 400:
        logger.warning("DocuSign document download failed: %s %s", response.status_code, response.text)
        raise DocuSignEnvelopeError(_error_detail(response))
    return response.content


async def _access_token() -> str:
    now = int(time.time())
    assertion = jwt.encode(
        {
            "iss": settings.docusign_integration_key,
            "sub": settings.docusign_user_id,
            "aud": settings.docusign_auth_server,
            "iat": now,
            "exp": now + 3600,
            "scope": "signature impersonation",
        },
        _private_key(),
        algorithm="RS256",
    )
    url = f"https://{settings.docusign_auth_server}/oauth/token"
    data = {
        "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
        "assertion": assertion,
    }
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(url, data=data)

    if response.status_code >= 400:
        logger.warning("DocuSign token request failed: %s %s", response.status_code, response.text)
        raise DocuSignEnvelopeError(_error_detail(response))
    return str(response.json()["access_token"])


def _private_key() -> str:
    key = settings.docusign_private_key.strip()
    if "\\n" in key:
        key = key.replace("\\n", "\n")
    return key


def _auth_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _error_detail(response: httpx.Response) -> str:
    try:
        data = response.json()
    except ValueError:
        return response.text or f"DocuSign API error {response.status_code}"
    return str(data.get("message") or data.get("error_description") or data.get("error") or data)
