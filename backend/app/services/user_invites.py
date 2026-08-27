from __future__ import annotations

import asyncio
import base64
import html
import logging
import os
import smtplib
from email.message import EmailMessage

from app.core.config import settings


logger = logging.getLogger(__name__)
GMAIL_SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"


async def send_user_invite(*, recipient: str, full_name: str) -> None:
    subject = "You've been invited to Office Hub"
    safe_name = html.escape(full_name)
    body = (
        '<div style="font-family:sans-serif;color:#222;line-height:1.5">'
        f"<p>Hi {safe_name},</p>"
        "<p>You've been invited to Office Hub.</p>"
        '<p><a href="https://officehub.n10z.ca" '
        'style="background:#1A527A;color:white;padding:12px 20px;border-radius:4px;'
        'text-decoration:none;font-weight:bold">Open Office Hub</a></p>'
        "<p>If you were not expecting this invitation, you can ignore this message.</p>"
        "</div>"
    )
    await asyncio.to_thread(_send, settings.gmail_sender_email, recipient, subject, body)
    logger.info("User invite email accepted by Gmail for %s", recipient)


def _send(sender: str, recipient: str, subject: str, body: str) -> None:
    password = settings.gmail_sender_app_password or (
        settings.imap_password
        if settings.imap_user.casefold() == sender.casefold()
        else ""
    )
    message = _message(sender, recipient, subject, body)
    if password:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as client:
            client.login(sender, password)
            client.send_message(message)
        return
    _send_oauth(message)


def _send_oauth(message: EmailMessage) -> None:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    token_path = os.path.expanduser(settings.google_oauth_token_path)
    if not os.path.exists(token_path):
        raise RuntimeError("Google OAuth authorization is required before sending user invites")
    credentials = Credentials.from_authorized_user_file(token_path)
    if not credentials.has_scopes([GMAIL_SEND_SCOPE]):
        raise RuntimeError(
            "Google OAuth token does not include gmail.send; reauthorization is required"
        )
    if credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())
        temporary_path = f"{token_path}.tmp"
        with open(temporary_path, "w", encoding="utf-8") as token_file:
            token_file.write(credentials.to_json())
        os.chmod(temporary_path, 0o600)
        os.replace(temporary_path, token_path)
    if not credentials.valid:
        raise RuntimeError("Google OAuth authorization is invalid; reauthorization is required")

    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    try:
        (
            build("gmail", "v1", credentials=credentials, cache_discovery=False)
            .users()
            .messages()
            .send(userId="me", body={"raw": raw})
            .execute()
        )
    except Exception as exc:
        raise RuntimeError(f"Gmail API could not send the user invite: {exc}") from exc


def _message(sender: str, recipient: str, subject: str, body: str) -> EmailMessage:
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = sender
    message["To"] = recipient
    message.set_content("You've been invited to Office Hub. Visit https://officehub.n10z.ca")
    message.add_alternative(body, subtype="html")
    return message
