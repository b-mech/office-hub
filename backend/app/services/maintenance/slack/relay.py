from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Protocol

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.maintenance import (
    MaintDirection,
    MaintEvent,
    MaintEventChannel,
    MaintParty,
    MaintSlackCard,
    MaintSmsMessage,
    MaintStatus,
    MaintTicket,
    MaintVendor,
    MaintVisibility,
    MaintWorkOrder,
)
from app.services.maintenance.media import store_attachment, validate_file_count
from app.services.maintenance.permissions import has_maintenance_permission
from app.services.maintenance.slack.render import render_cancel_button
from app.services.maintenance.slack.types import RelayResult
from app.services.maintenance.slack.users import resolve_slack_user
from app.services.maintenance.sms.outbound import queue_sms


logger = logging.getLogger("uvicorn.error")
logging.getLogger("httpx").setLevel(logging.WARNING)


class RelaySlackClient(Protocol):
    async def users_lookupByEmail(self, **kwargs: object) -> object: ...
    async def reactions_add(self, **kwargs: object) -> object: ...
    async def chat_postEphemeral(self, **kwargs: object) -> object: ...
    async def chat_postMessage(self, **kwargs: object) -> object: ...


BLOCKED_RELAY_STATUSES = {MaintStatus.CLOSED, MaintStatus.CANCELLED, MaintStatus.DUPLICATE}


def internal_note_body(text: str, thread_party: MaintParty) -> str | None:
    stripped = text.strip()
    if thread_party == MaintParty.STAFF:
        if stripped.startswith("//"):
            return stripped[2:].strip()
        if stripped.casefold().startswith("note:"):
            return stripped[5:].strip()
        return stripped
    if stripped.startswith("//"):
        return stripped[2:].strip()
    if stripped.casefold().startswith("note:"):
        return stripped[5:].strip()
    return None


async def _download_slack_files(
    db: AsyncSession,
    event: Mapping[str, object],
    *,
    ticket_id: object,
    work_order_id: object | None,
) -> list[object]:
    files = event.get("files")
    if not isinstance(files, list):
        return []
    validate_file_count(len(files), party=MaintParty.STAFF)
    attachment_ids: list[object] = []
    headers = {"Authorization": f"Bearer {settings.slack_bot_token}"}
    async with httpx.AsyncClient(timeout=30, headers=headers) as client:
        for item in files:
            if not isinstance(item, Mapping):
                continue
            url = str(item.get("url_private_download") or item.get("url_private") or "")
            if not url:
                continue
            response = await client.get(url)
            response.raise_for_status()
            attachment = await store_attachment(
                db,
                ticket_id=ticket_id,  # type: ignore[arg-type]
                work_order_id=work_order_id,  # type: ignore[arg-type]
                content=response.content,
                original_filename=str(item.get("name") or "slack-upload"),
                uploaded_by_party=MaintParty.STAFF,
            )
            attachment_ids.append(attachment.id)
    return attachment_ids


async def handle_thread_message(
    db: AsyncSession,
    client: RelaySlackClient,
    event: Mapping[str, object],
) -> RelayResult:
    if event.get("bot_id") or event.get("subtype"):
        return RelayResult("ignored", reason="bot_or_subtype")
    channel_id = str(event.get("channel") or "")
    thread_ts = str(event.get("thread_ts") or "")
    slack_ts = str(event.get("ts") or "")
    slack_user_id = str(event.get("user") or "")
    if not channel_id or not thread_ts or not slack_ts or not slack_user_id:
        return RelayResult("ignored", reason="not_thread_reply")
    if channel_id not in {settings.slack_tickets_channel_id, settings.slack_emergency_channel_id}:
        return RelayResult("ignored", reason="unconfigured_channel")
    card = await db.scalar(
        select(MaintSlackCard).where(
            MaintSlackCard.channel_id == channel_id,
            MaintSlackCard.message_ts == thread_ts,
        )
    )
    if card is None:
        return RelayResult("ignored", reason="unknown_thread")
    user = await resolve_slack_user(db, client, slack_user_id)
    if user is None:
        await client.chat_postEphemeral(
            channel=channel_id,
            user=slack_user_id,
            thread_ts=thread_ts,
            text="Your Slack account is not linked to an active Office Hub user.",
        )
        return RelayResult("blocked", reason="unlinked_user")
    text = str(event.get("text") or "").strip()
    note = internal_note_body(text, MaintParty(card.thread_party))
    if note is not None:
        if not has_maintenance_permission(user, "view"):
            return RelayResult("blocked", reason="permission")
        if not note:
            return RelayResult("blocked", reason="empty_internal_note")
        db.add(
            MaintEvent(
                ticket_id=card.ticket_id,
                work_order_id=card.work_order_id,
                event_type="internal_note",
                channel=MaintEventChannel.SLACK,
                visibility=MaintVisibility.INTERNAL,
                direction=MaintDirection.NONE,
                actor_party=MaintParty.STAFF,
                actor_user_id=user.id,
                body=note,
                slack_ts=slack_ts,
            )
        )
        await db.flush()
        try:
            await client.reactions_add(channel=channel_id, timestamp=slack_ts, name="lock")
        except Exception:
            logger.warning("Could not add internal-note Slack reaction")
        return RelayResult("internal")
    if not has_maintenance_permission(user, "message_external"):
        return RelayResult("blocked", reason="permission")
    ticket = await db.get(MaintTicket, card.ticket_id)
    if ticket is None:
        return RelayResult("blocked", reason="ticket_missing")
    status = MaintStatus(ticket.status)
    if status in BLOCKED_RELAY_STATUSES:
        elements: list[dict[str, object]] = []
        if status == MaintStatus.CLOSED and has_maintenance_permission(user, "admin"):
            elements.append(
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Reopen"},
                    "action_id": "maint_reopen",
                    "value": str(ticket.id),
                }
            )
        await client.chat_postEphemeral(
            channel=channel_id,
            user=slack_user_id,
            thread_ts=thread_ts,
            text=f"SMS relay is blocked while this ticket is {status.value}.",
            **({"blocks": [{"type": "actions", "elements": elements}]} if elements else {}),
        )
        return RelayResult("blocked", reason=status.value)
    existing = await db.scalar(
        select(MaintSmsMessage).where(
            MaintSmsMessage.slack_channel_id == channel_id,
            MaintSmsMessage.slack_ts == slack_ts,
        )
    )
    if existing is not None:
        return RelayResult("duplicate", message_id=existing.id)
    if not text and not event.get("files"):
        return RelayResult("blocked", reason="empty_message")
    recipient = ticket.reporter_phone_e164
    if MaintParty(card.thread_party) == MaintParty.VENDOR:
        work_order = await db.get(MaintWorkOrder, card.work_order_id)
        vendor = await db.get(MaintVendor, work_order.vendor_id) if work_order else None
        recipient = vendor.phone_e164 if vendor else None
    if not recipient:
        return RelayResult("blocked", reason="recipient_missing")
    attachments = await _download_slack_files(
        db,
        event,
        ticket_id=ticket.id,
        work_order_id=card.work_order_id,
    )
    message = await queue_sms(
        db,
        to=recipient,
        body=text or "Photo attached",
        ticket_id=ticket.id,
        work_order_id=card.work_order_id,
        media_attachment_ids=attachments,  # type: ignore[arg-type]
        automated=False,
        actor_party=MaintParty.STAFF,
        slack_channel_id=channel_id,
        slack_ts=slack_ts,
    )
    try:
        await client.reactions_add(
            channel=channel_id,
            timestamp=slack_ts,
            name="hourglass_flowing_sand",
        )
        await client.chat_postEphemeral(
            channel=channel_id,
            user=slack_user_id,
            thread_ts=thread_ts,
            text="SMS held briefly before sending.",
            blocks=render_cancel_button(message.id),
        )
    except Exception:
        logger.warning("Could not add held-SMS Slack controls")
    return RelayResult("held", message_id=message.id)


async def handle_edited_message(
    db: AsyncSession,
    client: RelaySlackClient,
    event: Mapping[str, object],
) -> RelayResult:
    message = event.get("message")
    if event.get("subtype") != "message_changed" or not isinstance(message, Mapping):
        return RelayResult("ignored")
    channel_id = str(event.get("channel") or "")
    slack_ts = str(message.get("ts") or "")
    queued = await db.scalar(
        select(MaintSmsMessage).where(
            MaintSmsMessage.slack_channel_id == channel_id,
            MaintSmsMessage.slack_ts == slack_ts,
        )
    )
    if queued is None:
        return RelayResult("ignored")
    await client.chat_postMessage(
        channel=channel_id,
        thread_ts=str(message.get("thread_ts") or ""),
        text="The Slack reply was edited after it was queued; the SMS content was not changed.",
    )
    return RelayResult("edit_notice", message_id=queued.id)
