from __future__ import annotations

import asyncio
import html
import smtplib
from datetime import datetime, timezone
from email.message import EmailMessage
from urllib.parse import urlparse

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.sales import ChangeOrder
from app.services.change_orders.pdf import render_change_order_pdf
from app.services.docusign import send_for_signature


def validate_payment_link(value: str) -> str:
    link = value.strip()
    parsed = urlparse(link)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Plooto payment link must be a valid http or https URL")
    return link


async def prepare_for_signature(db: AsyncSession, change_order: ChangeOrder) -> None:
    if not change_order.customer_email:
        raise ValueError("No client email on file. Please add it before continuing.")
    if change_order.status not in {"draft", "awaiting_payment_link"}:
        raise ValueError("Only draft change orders can start the signature workflow")
    change_order.plooto_status = "awaiting_link"
    change_order.status = "awaiting_payment_link"
    await db.commit()


async def save_payment_link_and_send(db: AsyncSession, change_order: ChangeOrder, link: str) -> str:
    if change_order.status != "awaiting_payment_link":
        raise ValueError("Change order is not awaiting a Plooto payment link")
    change_order.plooto_payment_link = validate_payment_link(link)
    change_order.plooto_status = "link_received"
    await db.commit()
    return await send_to_docusign(db, change_order)


async def send_to_docusign(db: AsyncSession, change_order: ChangeOrder, *, signer_name: str = "") -> str:
    if change_order.plooto_status != "link_received" or not change_order.plooto_payment_link:
        raise ValueError("Paste the Plooto payment link before sending to DocuSign")
    client_email = settings.docusign_test_recipient_email.strip() or (change_order.customer_email or "").strip()
    client_name = settings.docusign_test_recipient_name.strip() or signer_name.strip() or change_order.client_name
    if not client_email:
        raise ValueError("No client email on file")
    pdf_bytes = render_change_order_pdf(change_order)
    envelope_id, _ = await asyncio.to_thread(send_for_signature, change_order_id=str(change_order.id), address=change_order.address, client_name=client_name, client_email=client_email, pdf_bytes=pdf_bytes, co_number=change_order.co_number)
    if not envelope_id:
        raise RuntimeError("DocuSign is not configured or the request failed")
    change_order.docusign_envelope_id = envelope_id
    change_order.status = "sent"
    await db.commit()
    return envelope_id


async def send_payment_email(db: AsyncSession, change_order: ChangeOrder) -> bool:
    if change_order.payment_email_sent_at or not change_order.plooto_payment_link or not change_order.customer_email:
        return False
    sender = settings.gmail_sender_email
    password = settings.gmail_sender_app_password or (settings.imap_password if settings.imap_user.casefold() == sender.casefold() else "")
    if not password:
        raise RuntimeError("GMAIL_SENDER_APP_PASSWORD is not configured for yana@connectionhomes.ca")
    subject = "Change Order Approved — Payment Required to Proceed"
    body = _payment_html(change_order)
    await asyncio.to_thread(_smtp_send, sender, password, change_order.customer_email, subject, body)
    change_order.payment_email_sent_at = datetime.now(timezone.utc)
    await db.commit()
    return True


def _smtp_send(sender: str, password: str, recipient: str, subject: str, body: str) -> None:
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = sender
    message["To"] = recipient
    message.set_content("Your signed change order is ready for payment. Please use the payment link in the HTML version of this message.")
    message.add_alternative(body, subtype="html")
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as client:
        client.login(sender, password)
        client.send_message(message)


def _payment_html(change_order: ChangeOrder) -> str:
    customer = html.escape(change_order.client_name)
    address = html.escape(change_order.address)
    amount = f"${change_order.total:,.2f}"
    link = html.escape(change_order.plooto_payment_link or "", quote=True)
    return f"""<div style="font-family:sans-serif;color:#222;line-height:1.5"><p>Hi {customer},</p><p>Thank you for signing the change order for {address}. We're ready to move forward with this work.</p><p>To keep your construction schedule on track, please submit payment for this change order as soon as possible.</p><p><strong>Amount due: {amount}</strong></p><p><a href="{link}" style="background-color:#1A527A;color:#ffffff;padding:12px 24px;text-decoration:none;border-radius:4px;display:inline-block;font-weight:bold;font-family:sans-serif;">Pay Now</a></p><p>Please pay now to avoid construction delays — work on this change order is scheduled to begin once payment is received.</p><p>If you have any questions about this change order or the payment process, just reply to this email or give us a call.</p><p>Thank you,<br>Connection Homes</p></div>"""
