from __future__ import annotations

from datetime import datetime, timezone
import json
from uuid import UUID

from app.services.maintenance.slack.types import TicketCardView, WorkOrderCardView


def _plain(value: object, limit: int = 150) -> str:
    text = " ".join(str(value).split())
    return text if len(text) <= limit else f"{text[: limit - 1]}…"


def _mrkdwn(value: object, limit: int = 2800) -> str:
    text = str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return text if len(text) <= limit else f"{text[: limit - 1]}…"


def _label(value: str | None) -> str:
    return value.replace("_", " ").title() if value else "Not set"


def _metadata(entity_id: UUID, **extra: object) -> str:
    return json.dumps({"id": str(entity_id), **extra}, separators=(",", ":"))


def render_ticket_card(view: TicketCardView, *, now: datetime | None = None) -> list[dict[str, object]]:
    now = now or datetime.now(timezone.utc)
    marker = "🚨" if view.is_emergency else "🛠️"
    blocks: list[dict[str, object]] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": _plain(f"{marker} {view.number} · {view.title}")},
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": _mrkdwn(f"*{view.property_label}* · {view.unit_label}"),
                }
            ],
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Status*\n{_label(view.status)}"},
                {"type": "mrkdwn", "text": f"*Priority*\n{_label(view.priority)}"},
                {"type": "mrkdwn", "text": f"*Category*\n{_label(view.category)}"},
                {"type": "mrkdwn", "text": f"*Entry*\n{_label(view.entry_permission)}"},
            ],
        },
        {"type": "section", "text": {"type": "mrkdwn", "text": _mrkdwn(view.description)}},
    ]
    warnings: list[str] = []
    if not view.reporter_verified:
        warnings.append("⚠️ Reporter is not verified against the current lease.")
    if view.is_emergency and not view.emergency_acknowledged:
        warnings.append("🚨 Emergency has not been acknowledged.")
    if view.sla_due_at:
        if view.sla_due_at <= now:
            warnings.append(f"⚠️ SLA overdue since {view.sla_due_at.isoformat()}.")
        else:
            warnings.append(f"⏱️ SLA due {view.sla_due_at.isoformat()}.")
    if warnings:
        blocks.append(
            {"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(warnings)}}
        )
    reporter = _plain(view.reporter_name or "Unknown reporter")
    blocks.append(
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": _mrkdwn(
                        f"Reporter: {reporter} · Attachments: {view.attachment_count} · "
                        f"Work orders: {len(view.work_orders)}"
                    ),
                }
            ],
        }
    )
    if view.ai_suggestion:
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": _mrkdwn(f"*AI suggestion — review before acting*\n{view.ai_suggestion}"),
                },
            }
        )
    actions: list[dict[str, object]] = []
    if view.is_emergency and not view.emergency_acknowledged:
        actions.append(
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Acknowledge"},
                "style": "danger",
                "action_id": "maint_ack_emergency",
                "value": str(view.id),
            }
        )
    if view.status == "new":
        actions.append(
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Triage"},
                "style": "primary",
                "action_id": "maint_open_triage",
                "value": str(view.id),
            }
        )
    if view.status in {"triaged", "assigned"}:
        actions.append(
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Assign"},
                "action_id": "maint_open_assign",
                "value": str(view.id),
            }
        )
    if view.status not in {"closed", "cancelled", "duplicate"}:
        actions.append(
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Message"},
                "action_id": "maint_open_message",
                "value": str(view.id),
            }
        )
    if view.status == "closed":
        actions.append(
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Reopen"},
                "action_id": "maint_reopen",
                "value": str(view.id),
            }
        )
    elif view.status in {"in_progress", "awaiting_parts", "awaiting_tenant", "resolved"}:
        actions.append(
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Resolve"},
                "action_id": "maint_open_resolve",
                "value": str(view.id),
            }
        )
    if view.status in {"new", "triaged"}:
        actions.append(
            {
                "type": "overflow",
                "action_id": "maint_more",
                "options": [
                    {
                        "text": {"type": "plain_text", "text": "Cancel ticket"},
                        "value": _metadata(view.id, operation="cancel"),
                    },
                    {
                        "text": {"type": "plain_text", "text": "Mark duplicate"},
                        "value": _metadata(view.id, operation="duplicate"),
                    },
                ],
            }
        )
    if actions:
        blocks.append({"type": "actions", "elements": actions[:5]})
    return blocks


def render_work_order_card(view: WorkOrderCardView, ticket_id: UUID) -> list[dict[str, object]]:
    party = "Internal staff" if view.assignee_type == "staff" else "Vendor relay"
    schedule = (
        f"{view.scheduled_start.isoformat()} – {view.scheduled_end.isoformat()}"
        if view.scheduled_start and view.scheduled_end
        else "Not scheduled"
    )
    return [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": _plain(f"🔧 {view.number} · {view.assignee_name}")},
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Status*\n{_label(view.status)}"},
                {"type": "mrkdwn", "text": f"*Thread*\n{party}"},
                {"type": "mrkdwn", "text": f"*Schedule*\n{_mrkdwn(schedule)}"},
            ],
        },
        {"type": "section", "text": {"type": "mrkdwn", "text": _mrkdwn(view.scope)}},
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Schedule"},
                    "action_id": "maint_open_schedule",
                    "value": _metadata(ticket_id, work_order_id=str(view.id)),
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Complete"},
                    "action_id": "maint_open_complete_work_order",
                    "value": _metadata(ticket_id, work_order_id=str(view.id)),
                },
            ],
        },
    ]


def render_emergency_alert(view: TicketCardView) -> list[dict[str, object]]:
    return [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": _plain(f"🚨 {view.number} · {view.title}")},
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": _mrkdwn(f"*{view.property_label} · {view.unit_label}*\n{view.description}"),
            },
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Acknowledge"},
                    "style": "danger",
                    "action_id": "maint_ack_emergency",
                    "value": str(view.id),
                }
            ],
        },
    ]


def render_cancel_button(message_id: UUID) -> list[dict[str, object]]:
    return [
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Cancel SMS"},
                    "style": "danger",
                    "action_id": "maint_cancel_held_sms",
                    "value": str(message_id),
                }
            ],
        }
    ]
