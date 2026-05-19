from __future__ import annotations

import json
import logging
from io import BytesIO
from pathlib import Path
from typing import Any

from boxsdk import Client
from boxsdk import OAuth2

from app.core.config import settings


logger = logging.getLogger(__name__)
_oauth_state: str | None = None


def _token_path() -> Path:
    path = Path(settings.box_token_file)
    return path if path.is_absolute() else Path.cwd() / path


def _store_tokens(access_token: str, refresh_token: str) -> None:
    token_path = _token_path()
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(
        json.dumps({"access_token": access_token, "refresh_token": refresh_token}),
        encoding="utf-8",
    )


def _load_tokens() -> dict[str, str] | None:
    token_path = _token_path()
    if not token_path.exists():
        return None
    try:
        data = json.loads(token_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Failed to load Box token file: %s", exc)
        return None

    access_token = data.get("access_token")
    refresh_token = data.get("refresh_token")
    if not isinstance(access_token, str) or not isinstance(refresh_token, str):
        logger.warning("Box token file is missing access_token or refresh_token")
        return None
    return {"access_token": access_token, "refresh_token": refresh_token}


def get_oauth_url() -> str:
    global _oauth_state
    oauth = OAuth2(client_id=settings.box_client_id, client_secret=settings.box_client_secret)
    auth_url, csrf_token = oauth.get_authorization_url(settings.box_redirect_uri)
    _oauth_state = csrf_token
    return auth_url


def handle_oauth_callback(code: str, state: str) -> bool:
    if not _oauth_state or state != _oauth_state:
        logger.warning("Box OAuth callback state mismatch")
        return False

    oauth = OAuth2(
        client_id=settings.box_client_id,
        client_secret=settings.box_client_secret,
        store_tokens=_store_tokens,
    )
    try:
        access_token, refresh_token = oauth.authenticate(code)
        _store_tokens(access_token, refresh_token)
    except Exception as exc:
        logger.warning("Box OAuth callback failed: %s", exc)
        return False
    return True


def get_box_client() -> Client | None:
    if not settings.box_configured:
        logger.warning("Box is not configured; folder IDs are missing")
        return None

    tokens = _load_tokens()
    if tokens is None:
        logger.warning("Box is not authenticated; token file is missing")
        return None

    try:
        oauth = OAuth2(
            client_id=settings.box_client_id,
            client_secret=settings.box_client_secret,
            access_token=tokens["access_token"],
            refresh_token=tokens["refresh_token"],
            store_tokens=_store_tokens,
        )
        return Client(oauth)
    except Exception as exc:
        logger.warning("Failed to create Box client: %s", exc)
        return None


def get_or_create_subfolder(parent_folder_id: str, folder_name: str) -> str | None:
    client = get_box_client()
    if client is None:
        return None

    try:
        parent = client.folder(parent_folder_id)
        for item in parent.get_items(limit=1000, fields=["id", "type", "name"]):
            if getattr(item, "type", None) == "folder" and getattr(item, "name", None) == folder_name:
                return str(item.id)
        return str(parent.create_subfolder(folder_name).id)
    except Exception as exc:
        logger.warning("Failed to get or create Box folder %s: %s", folder_name, exc)
        return None


def upload_file(
    folder_id: str,
    filename: str,
    content: bytes,
    content_type: str = "application/pdf",
) -> tuple[str | None, str | None]:
    del content_type
    client = get_box_client()
    if client is None:
        return None, None

    try:
        folder = client.folder(folder_id)
        existing_file_id: str | None = None
        for item in folder.get_items(limit=1000, fields=["id", "type", "name"]):
            if getattr(item, "type", None) == "file" and getattr(item, "name", None) == filename:
                existing_file_id = str(item.id)
                break

        stream = BytesIO(content)
        if existing_file_id:
            uploaded = client.file(existing_file_id).update_contents_with_stream(stream, file_name=filename)
        else:
            uploaded = folder.upload_stream(stream, filename)

        box_file_id = str(uploaded.id)
        return box_file_id, f"https://app.box.com/file/{box_file_id}"
    except Exception as exc:
        logger.warning("Failed to upload Box file %s: %s", filename, exc)
        return None, None


def file_change_order_pdf(
    address: str,
    pdf_bytes: bytes,
    signed: bool = False,
) -> tuple[str | None, str | None]:
    if not settings.box_configured or not settings.box_authenticated:
        logger.warning("Skipping Box filing; Box is not configured or authenticated")
        return None, None

    parent_folder_id = (
        settings.box_finalized_folder_id if signed else settings.box_not_finalized_folder_id
    )
    subfolder_name = f"1C - {address} - Change Orders"
    filename = f"{address}-signed.pdf" if signed else f"{address}.pdf"

    subfolder_id = get_or_create_subfolder(parent_folder_id, subfolder_name)
    if subfolder_id is None:
        return None, None
    return upload_file(
        folder_id=subfolder_id,
        filename=filename,
        content=pdf_bytes,
        content_type="application/pdf",
    )
