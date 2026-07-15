from __future__ import annotations

import re
from datetime import date

import boto3
from botocore.client import Config

from app.core.config import settings


FINANCING_BUCKET = "documents"


def financing_key(lender_type: str, filename: str, address: str | None = None) -> str:
    safe_name = _safe_filename(address or filename)
    suffix = filename.rsplit(".", 1)[-1].lower() if "." in filename else "bin"
    return f"financing/{lender_type.lower()}/{date.today().isoformat()}_{safe_name}.{suffix}"


def upload_financing_document(*, key: str, content: bytes, content_type: str) -> None:
    client = _s3_client()
    _ensure_bucket(client)
    client.put_object(
        Bucket=FINANCING_BUCKET,
        Key=key,
        Body=content,
        ContentType=content_type,
    )


def delete_financing_document(*, key: str) -> None:
    _s3_client().delete_object(Bucket=FINANCING_BUCKET, Key=key)


def _s3_client():
    return boto3.client(
        "s3",
        endpoint_url=settings.minio_url,
        aws_access_key_id=settings.minio_root_user,
        aws_secret_access_key=settings.minio_root_password,
        region_name="us-east-1",
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )


def _ensure_bucket(client) -> None:
    try:
        client.head_bucket(Bucket=FINANCING_BUCKET)
    except Exception:
        client.create_bucket(Bucket=FINANCING_BUCKET)


def _safe_filename(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "-", value).strip("-")
    return cleaned[:120] or "document"
