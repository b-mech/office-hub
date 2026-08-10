from __future__ import annotations

import json
import logging
from io import BytesIO
from pathlib import Path

from boxsdk import Client
from boxsdk import OAuth2

from app.core.config import settings


# BOX FOLDER STRUCTURE FOR CHANGE ORDERS
#
# Unsigned: [Area] / 1C - {address} - Change Orders /
#             To Be Signed / {address}.pdf
# Signed:   [Area] / 1C - {address} - Change Orders /
#             {address}-signed.pdf
#
# OH finds the correct folder by searching Box for
# "1C - {address} - Change Orders". The Area is not needed.
#
# If the folder is not found, files go to the Unfiled
# Change Orders folder (BOX_UNFILED_FOLDER_ID in .env).
# Create this folder in Box and add its ID to .env.
# Manually move unfiled documents once the correct Box
# folder is created.

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
    if not settings.box_client_id or not settings.box_client_secret:
        logger.warning("Box is not configured; client credentials are missing")
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


def get_or_create_subfolder(parent_folder_id: str, folder_name: str, *, raise_errors: bool = False) -> str | None:
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
        if raise_errors:
            status = getattr(exc, "status", None)
            code = getattr(exc, "code", None)
            raise RuntimeError(f"Box folder error ({status or 'no status'}/{code or type(exc).__name__}): {exc}") from exc
        return None


def find_folder_by_name(name: str, parent_folder_id: str = "0") -> str | None:
    client = get_box_client()
    if client is None:
        return None

    logger.info("Searching Box for folder named %r under parent %s", name, parent_folder_id)
    try:
        ancestor_folders = None
        if parent_folder_id != "0":
            ancestor_folders = [client.folder(parent_folder_id)]

        results = client.search().query(
            query=name,
            type="folder",
            ancestor_folders=ancestor_folders,
            fields=["id", "type", "name"],
            limit=100,
        )
        for result in results:
            if getattr(result, "type", None) == "folder" and getattr(result, "name", None) == name:
                folder_id = str(result.id)
                logger.info("Found Box folder %r: %s", name, folder_id)
                return folder_id

        logger.info("No exact Box folder match found for %r", name)
        return None
    except Exception as exc:
        logger.warning("Failed to search Box for folder %r: %s", name, exc)
        return None


def upload_file(
    folder_id: str,
    filename: str,
    content: bytes,
    content_type: str = "application/pdf",
    *,
    raise_errors: bool = False,
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
        if raise_errors:
            status = getattr(exc, "status", None)
            code = getattr(exc, "code", None)
            raise RuntimeError(f"Box upload error ({status or 'no status'}/{code or type(exc).__name__}): {exc}") from exc
        return None, None


def delete_file(file_id: str) -> bool:
    client = get_box_client()
    if client is None:
        return False
    try:
        client.file(file_id).delete()
        return True
    except Exception as exc:
        logger.warning("Failed to delete Box file %s: %s", file_id, exc)
        return False


def file_change_order_pdf(
    address: str,
    pdf_bytes: bytes,
    signed: bool = False,
) -> tuple[str | None, str | None, bool]:
    if not settings.box_configured or not settings.box_authenticated:
        logger.warning("Skipping Box filing; Box is not configured or authenticated")
        return None, None, False

    folder_address = _box_change_order_folder_address(address)
    folder_name = f"1C - {folder_address} - Change Orders"
    folder_id = find_folder_by_name(folder_name)
    filed_to_unfiled = False

    if folder_id is not None:
        parent_folder_id = folder_id
        filename = f"{folder_address}-signed.pdf" if signed else f"{folder_address}.pdf"
        if not signed:
            to_be_signed_folder_id = get_or_create_subfolder(folder_id, "To Be Signed")
            if to_be_signed_folder_id is None:
                return None, None, False
            parent_folder_id = to_be_signed_folder_id
    else:
        logger.warning(
            "Box folder not found for address '%s' - filing to Unfiled Change Orders",
            address,
        )
        parent_folder_id = settings.box_unfiled_folder_id
        if not parent_folder_id:
            logger.warning("Skipping Box filing; BOX_UNFILED_FOLDER_ID is not configured")
            return None, None, False
        filed_to_unfiled = True
        filename = f"UNFILED - {folder_address}-signed.pdf" if signed else f"UNFILED - {folder_address}.pdf"

    box_file_id, box_file_url = upload_file(
        folder_id=parent_folder_id,
        filename=filename,
        content=pdf_bytes,
        content_type="application/pdf",
    )
    if box_file_id is None:
        return None, None, filed_to_unfiled
    return box_file_id, box_file_url, filed_to_unfiled


def _box_change_order_folder_address(address: str) -> str:
    return address.split(",", 1)[0].strip() or address.strip()
