from __future__ import annotations

import base64
import logging
import time
from dataclasses import dataclass

from docusign_esign import ApiClient
from docusign_esign import DateSigned
from docusign_esign import Document
from docusign_esign import EnvelopeDefinition
from docusign_esign import EnvelopesApi
from docusign_esign import Recipients
from docusign_esign import SignHere
from docusign_esign import Signer
from docusign_esign import Tabs

from app.core.config import settings


logger = logging.getLogger(__name__)


@dataclass
class _TokenCache:
    access_token: str = ""
    expires_at: int = 0


_token_cache = _TokenCache()


def get_docusign_client() -> ApiClient | None:
    if not settings.docusign_configured:
        logger.warning("DocuSign is not configured; DOCUSIGN_PRIVATE_KEY is required.")
        return None

    try:
        private_key = _private_key_bytes()
    except ValueError as exc:
        logger.error("DocuSign private key is malformed: %s", exc)
        return None

    api_client = ApiClient()
    api_client.host = _rest_api_base_path()

    now = int(time.time())
    if _token_cache.access_token and _token_cache.expires_at > now + 300:
        api_client.set_default_header("Authorization", f"Bearer {_token_cache.access_token}")
        return api_client

    try:
        # JWT requires one-time user consent before token exchange works. Consent URL:
        # https://demo.docusign.net/oauth/auth?response_type=code&scope=signature%20impersonation&client_id=f799edf4-90bc-4c55-9f66-e52ca8dcaad6&redirect_uri=https://demo.docusign.net
        token = api_client.request_jwt_user_token(
            client_id=settings.docusign_integration_key,
            user_id=settings.docusign_user_id,
            oauth_host_name=settings.docusign_auth_server,
            private_key_bytes=private_key,
            expires_in=3600,
            scopes=["signature", "impersonation"],
        )
    except Exception as exc:
        logger.error("DocuSign JWT authentication failed: %s", exc)
        return None

    _token_cache.access_token = token.access_token
    _token_cache.expires_at = now + int(getattr(token, "expires_in", 3600) or 3600)
    api_client.set_default_header("Authorization", f"Bearer {_token_cache.access_token}")
    return api_client


def send_for_signature(
    change_order_id: str,
    address: str,
    client_name: str,
    client_email: str,
    pdf_bytes: bytes,
    co_number: str | None = None,
) -> tuple[str, str] | tuple[None, None]:
    del change_order_id
    api_client = get_docusign_client()
    if api_client is None:
        return None, None

    label = co_number or "Draft"
    document_name = f"{address} - Change Order {label}"
    try:
        envelope = EnvelopeDefinition(
            email_subject=f"Please sign: Change Order {label} - {address}",
            email_blurb=(
                f"Please review and sign the attached change order for {address}. "
                "If you have any questions please contact accounts@connectionhomes.ca"
            ),
            documents=[
                Document(
                    document_base64=base64.b64encode(pdf_bytes).decode("ascii"),
                    name=document_name,
                    file_extension="pdf",
                    document_id="1",
                )
            ],
            recipients=Recipients(
                signers=[
                    Signer(
                        email=client_email,
                        name=client_name,
                        recipient_id="1",
                        routing_order="1",
                        tabs=Tabs(
                            sign_here_tabs=[
                                SignHere(
                                    anchor_string="Purchaser Signature",
                                    anchor_units="pixels",
                                    anchor_y_offset="-25",
                                    anchor_x_offset="0",
                                )
                            ],
                            date_signed_tabs=[
                                DateSigned(
                                    anchor_string="Date",
                                    anchor_units="pixels",
                                    anchor_y_offset="-25",
                                    anchor_x_offset="0",
                                )
                            ],
                        ),
                    )
                ]
            ),
            status="sent",
        )
        result = EnvelopesApi(api_client).create_envelope(
            account_id=settings.docusign_account_id,
            envelope_definition=envelope,
        )
    except Exception as exc:
        logger.error("DocuSign envelope creation failed: %s", exc)
        return None, None

    envelope_id = str(getattr(result, "envelope_id", "") or "")
    if not envelope_id:
        logger.error("DocuSign envelope creation returned no envelope ID.")
        return None, None
    return envelope_id, f"{settings.docusign_base_url.rstrip('/')}/monitor"


def get_signed_pdf(envelope_id: str) -> bytes | None:
    api_client = get_docusign_client()
    if api_client is None:
        return None

    try:
        document = EnvelopesApi(api_client).get_document(
            account_id=settings.docusign_account_id,
            document_id="combined",
            envelope_id=envelope_id,
        )
    except Exception as exc:
        logger.error("DocuSign signed PDF download failed for envelope %s: %s", envelope_id, exc)
        return None

    if isinstance(document, bytes):
        return document
    if isinstance(document, str):
        with open(document, "rb") as pdf_file:
            return pdf_file.read()
    logger.error("DocuSign returned unexpected document payload for envelope %s", envelope_id)
    return None


def _rest_api_base_path() -> str:
    return settings.docusign_base_path or f"{settings.docusign_base_url.rstrip('/')}/restapi"


def _private_key_bytes() -> bytes:
    key = settings.docusign_private_key.strip()
    if "\\n" in key:
        key = key.replace("\\n", "\n")
    if "BEGIN" not in key or "PRIVATE KEY" not in key:
        raise ValueError("missing RSA private key PEM header")
    return key.encode("utf-8")
