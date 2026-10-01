from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import io
import json
import time
from dataclasses import dataclass
from uuid import UUID, uuid4

import boto3
from botocore.client import Config
from PIL import Image, ImageOps
from pillow_heif import register_heif_opener
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.maintenance import MaintAttachment, MaintParty
from app.services.maintenance.errors import InvalidMediaError


MAINTENANCE_BUCKET = "documents"
MAX_FILE_BYTES = 10 * 1024 * 1024
IMAGE_TYPES = {"image/jpeg", "image/png", "image/heic", "image/webp"}


@dataclass(frozen=True)
class ProcessedMedia:
    content: bytes
    content_type: str
    extension: str


def detect_content_type(content: bytes) -> str:
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "image/webp"
    if len(content) >= 12 and content[4:8] == b"ftyp":
        brands = content[8:40]
        if any(brand in brands for brand in (b"heic", b"heix", b"hevc", b"hevx", b"mif1", b"msf1")):
            return "image/heic"
    if content.startswith(b"%PDF-"):
        return "application/pdf"
    raise InvalidMediaError("File type is not supported")


def process_media(content: bytes, *, kind: str = "photo") -> ProcessedMedia:
    if len(content) > MAX_FILE_BYTES:
        raise InvalidMediaError("Files must be 10 MB or smaller")
    if not content:
        raise InvalidMediaError("The uploaded file is empty")
    detected = detect_content_type(content)
    if detected == "application/pdf":
        if kind != "invoice":
            raise InvalidMediaError("PDF files are accepted only for invoices")
        return ProcessedMedia(content, detected, "pdf")

    register_heif_opener()
    try:
        with Image.open(io.BytesIO(content)) as source:
            source.load()
            image = ImageOps.exif_transpose(source)
            output = io.BytesIO()
            if detected in {"image/jpeg", "image/heic"}:
                image.convert("RGB").save(output, format="JPEG", quality=90, optimize=True, exif=b"")
                return ProcessedMedia(output.getvalue(), "image/jpeg", "jpg")
            if detected == "image/png":
                image.save(output, format="PNG", optimize=True)
                return ProcessedMedia(output.getvalue(), "image/png", "png")
            image.save(output, format="WEBP", quality=90, method=6, exif=b"")
            return ProcessedMedia(output.getvalue(), "image/webp", "webp")
    except (OSError, ValueError) as exc:
        raise InvalidMediaError("The uploaded image is corrupt or unsupported") from exc


def validate_file_count(count: int, *, party: MaintParty) -> None:
    limit = 5 if party == MaintParty.TENANT else 10
    if count > limit:
        raise InvalidMediaError(f"A maximum of {limit} files is allowed")


async def store_attachment(
    db: AsyncSession,
    *,
    ticket_id: UUID | None,
    content: bytes,
    original_filename: str | None,
    uploaded_by_party: MaintParty,
    kind: str = "photo",
    work_order_id: UUID | None = None,
    event_id: UUID | None = None,
) -> MaintAttachment:
    processed = await asyncio.to_thread(process_media, content, kind=kind)
    attachment_id = uuid4()
    owner = str(ticket_id) if ticket_id is not None else "unmatched"
    key = f"maintenance/{owner}/{attachment_id}.{processed.extension}"
    await asyncio.to_thread(_upload, key, processed)
    attachment = MaintAttachment(
        id=attachment_id,
        ticket_id=ticket_id,
        work_order_id=work_order_id,
        event_id=event_id,
        minio_key=key,
        content_type=processed.content_type,
        size_bytes=len(processed.content),
        original_filename=original_filename,
        uploaded_by_party=uploaded_by_party,
        kind=kind,
    )
    db.add(attachment)
    await db.flush()
    return attachment


def create_signed_media_token(attachment_id: UUID, secret: str, *, expires_in_seconds: int = 3600, now: int | None = None) -> str:
    expires_at = (now if now is not None else int(time.time())) + expires_in_seconds
    payload = json.dumps({"attachment_id": str(attachment_id), "exp": expires_at}, separators=(",", ":")).encode()
    encoded = _b64encode(payload)
    signature = hmac.new(secret.encode(), encoded.encode(), hashlib.sha256).digest()
    return f"{encoded}.{_b64encode(signature)}"


def verify_signed_media_token(token: str, secret: str, *, now: int | None = None) -> UUID:
    try:
        encoded, supplied = token.split(".", 1)
        expected = _b64encode(hmac.new(secret.encode(), encoded.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(supplied, expected):
            raise ValueError
        payload = json.loads(_b64decode(encoded))
        if int(payload["exp"]) < (now if now is not None else int(time.time())):
            raise ValueError
        return UUID(payload["attachment_id"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise InvalidMediaError("Media link is invalid or expired") from exc


def _upload(key: str, media: ProcessedMedia) -> None:
    client = _s3_client()
    try:
        client.head_bucket(Bucket=MAINTENANCE_BUCKET)
    except Exception:
        client.create_bucket(Bucket=MAINTENANCE_BUCKET)
    client.put_object(
        Bucket=MAINTENANCE_BUCKET,
        Key=key,
        Body=media.content,
        ContentType=media.content_type,
    )


def download_attachment(key: str) -> bytes:
    response = _s3_client().get_object(Bucket=MAINTENANCE_BUCKET, Key=key)
    try:
        return response["Body"].read()
    finally:
        response["Body"].close()


def _s3_client():
    return boto3.client(
        "s3",
        endpoint_url=settings.minio_url,
        aws_access_key_id=settings.minio_root_user,
        aws_secret_access_key=settings.minio_root_password,
        region_name="us-east-1",
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
