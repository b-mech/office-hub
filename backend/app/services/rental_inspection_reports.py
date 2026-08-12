from __future__ import annotations

import asyncio
import base64
import hashlib
import html
import os
import secrets
import smtplib
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.rentals import RentalInspection, RentalInspectionReport, RentalInspectionReportItem

GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/gmail.send",
]


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def create_report(db: AsyncSession, title: str, inspection_ids: list[int], expires_in_days: int) -> tuple[RentalInspectionReport, str]:
    unique_ids = list(dict.fromkeys(inspection_ids))
    inspections = list((await db.scalars(select(RentalInspection).where(RentalInspection.id.in_(unique_ids), RentalInspection.status == "submitted"))).all())
    if len(inspections) != len(unique_ids):
        raise ValueError("Every selected inspection must exist and be submitted")
    token = secrets.token_urlsafe(32)
    report = RentalInspectionReport(title=title.strip(), token_hash=token_hash(token), expires_at=datetime.now(timezone.utc) + timedelta(days=expires_in_days))
    db.add(report)
    await db.flush()
    for order, inspection_id in enumerate(unique_ids):
        db.add(RentalInspectionReportItem(report_id=report.id, inspection_id=inspection_id, sort_order=order))
    await db.commit()
    await db.refresh(report)
    return report, token


async def send_report_email(db: AsyncSession, report: RentalInspectionReport, recipient: str, public_url: str) -> None:
    sender = settings.gmail_sender_email
    password = settings.gmail_sender_app_password or (settings.imap_password if settings.imap_user.casefold() == sender.casefold() else "")
    escaped_url = html.escape(public_url, quote=True)
    body = f'<div style="font-family:sans-serif;color:#222"><h2>{html.escape(report.title)}</h2><p>An inspection report is ready for your review.</p><p><a href="{escaped_url}" style="background:#1A527A;color:white;padding:12px 20px;border-radius:4px;text-decoration:none;font-weight:bold">Open Inspection Report</a></p><p>This secure link expires {report.expires_at.strftime("%B %d, %Y at %H:%M UTC")}.</p></div>'
    if password:
        await asyncio.to_thread(_send, sender, password, recipient, report.title, body)
    else:
        await asyncio.to_thread(_send_oauth, sender, recipient, report.title, body)
    report.recipient_email = recipient
    report.status = "sent"
    report.sent_at = datetime.now(timezone.utc)
    await db.commit()


def _send(sender: str, password: str, recipient: str, subject: str, body: str) -> None:
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = sender
    message["To"] = recipient
    message.set_content("An inspection report is ready. Open the secure link in the HTML email.")
    message.add_alternative(body, subtype="html")
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as client:
        client.login(sender, password)
        client.send_message(message)


def _send_oauth(sender: str, recipient: str, subject: str, body: str) -> None:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    token_path = os.path.expanduser(settings.google_oauth_token_path)
    if not os.path.exists(token_path):
        raise RuntimeError("Google OAuth authorization is required before sending reports")
    credentials = Credentials.from_authorized_user_file(token_path, GOOGLE_SCOPES)
    if not credentials.has_scopes([GOOGLE_SCOPES[1]]):
        raise RuntimeError("Google OAuth token does not include gmail.send; reauthorization is required")
    if credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())
        with open(token_path, "w", encoding="utf-8") as token_file:
            token_file.write(credentials.to_json())
    if not credentials.valid:
        raise RuntimeError("Google OAuth authorization is invalid; reauthorization is required")
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = sender
    message["To"] = recipient
    message.set_content("An inspection report is ready. Open the secure link in the HTML email.")
    message.add_alternative(body, subtype="html")
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    try:
        build("gmail", "v1", credentials=credentials, cache_discovery=False).users().messages().send(userId="me", body={"raw": raw}).execute()
    except Exception as exc:
        raise RuntimeError(f"Gmail API could not send the report: {exc}") from exc
