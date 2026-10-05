from __future__ import annotations

import json
from uuid import UUID

from app.models.maintenance import MaintCategory, MaintPriority


def _metadata(ticket_id: UUID, **values: object) -> str:
    return json.dumps({"ticket_id": str(ticket_id), **values}, separators=(",", ":"))


def _text_input(block_id: str, action_id: str, label: str, *, multiline: bool = False) -> dict[str, object]:
    element: dict[str, object] = {"type": "plain_text_input", "action_id": action_id}
    if multiline:
        element["multiline"] = True
    return {
        "type": "input",
        "block_id": block_id,
        "label": {"type": "plain_text", "text": label},
        "element": element,
    }


def triage_modal(ticket_id: UUID, title: str) -> dict[str, object]:
    return {
        "type": "modal",
        "callback_id": "maint_triage_submit",
        "private_metadata": _metadata(ticket_id),
        "title": {"type": "plain_text", "text": "Triage ticket"},
        "submit": {"type": "plain_text", "text": "Save"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": [
            {
                **_text_input("title", "value", "Title"),
                "element": {
                    "type": "plain_text_input",
                    "action_id": "value",
                    "initial_value": title[:150],
                },
            },
            {
                "type": "input",
                "block_id": "category",
                "label": {"type": "plain_text", "text": "Category"},
                "element": {
                    "type": "static_select",
                    "action_id": "value",
                    "options": [
                        {
                            "text": {"type": "plain_text", "text": item.value.replace("_", " ").title()},
                            "value": item.value,
                        }
                        for item in MaintCategory
                    ],
                },
            },
            {
                "type": "input",
                "block_id": "priority",
                "label": {"type": "plain_text", "text": "Priority"},
                "element": {
                    "type": "static_select",
                    "action_id": "value",
                    "options": [
                        {"text": {"type": "plain_text", "text": item.value.title()}, "value": item.value}
                        for item in MaintPriority
                    ],
                },
            },
            {
                "type": "input",
                "optional": True,
                "block_id": "emergency",
                "label": {"type": "plain_text", "text": "Emergency"},
                "element": {
                    "type": "checkboxes",
                    "action_id": "value",
                    "options": [
                        {"text": {"type": "plain_text", "text": "Treat as emergency"}, "value": "yes"}
                    ],
                },
            },
            {**_text_input("summary", "value", "Internal summary", multiline=True), "optional": True},
        ],
    }


def message_modal(ticket_id: UUID) -> dict[str, object]:
    return {
        "type": "modal",
        "callback_id": "maint_message_submit",
        "private_metadata": _metadata(ticket_id),
        "title": {"type": "plain_text", "text": "Message tenant"},
        "submit": {"type": "plain_text", "text": "Queue SMS"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": [_text_input("message", "value", "Message", multiline=True)],
    }


def resolve_modal(ticket_id: UUID) -> dict[str, object]:
    return {
        "type": "modal",
        "callback_id": "maint_resolve_submit",
        "private_metadata": _metadata(ticket_id),
        "title": {"type": "plain_text", "text": "Resolve ticket"},
        "submit": {"type": "plain_text", "text": "Mark resolved"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": [_text_input("reason", "value", "Resolution notes", multiline=True)],
    }


def assignment_modal(ticket_id: UUID, options: list[dict[str, object]]) -> dict[str, object]:
    return {
        "type": "modal",
        "callback_id": "maint_assign_submit",
        "private_metadata": _metadata(ticket_id),
        "title": {"type": "plain_text", "text": "Assign work"},
        "submit": {"type": "plain_text", "text": "Assign"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": [
            {
                "type": "input",
                "block_id": "assignee",
                "label": {"type": "plain_text", "text": "Assignee"},
                "element": {"type": "static_select", "action_id": "value", "options": options},
            },
            _text_input("scope", "value", "Scope", multiline=True),
            {**_text_input("estimate", "value", "Cost estimate"), "optional": True},
        ],
    }


def schedule_modal(ticket_id: UUID, work_order_id: UUID) -> dict[str, object]:
    return {
        "type": "modal",
        "callback_id": "maint_schedule_submit",
        "private_metadata": _metadata(ticket_id, work_order_id=str(work_order_id)),
        "title": {"type": "plain_text", "text": "Schedule work"},
        "submit": {"type": "plain_text", "text": "Schedule"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": [
            _text_input("start", "value", "Start (ISO 8601 with timezone)"),
            _text_input("end", "value", "End (ISO 8601 with timezone)"),
            {**_text_input("override", "value", "Admin override reason"), "optional": True},
        ],
    }


def complete_work_order_modal(ticket_id: UUID, work_order_id: UUID) -> dict[str, object]:
    return {
        "type": "modal",
        "callback_id": "maint_complete_work_order_submit",
        "private_metadata": _metadata(ticket_id, work_order_id=str(work_order_id)),
        "title": {"type": "plain_text", "text": "Complete work"},
        "submit": {"type": "plain_text", "text": "Complete"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": [
            _text_input("notes", "value", "Completion notes", multiline=True),
            {**_text_input("cost", "value", "Actual cost"), "optional": True},
        ],
    }


def cancel_modal(ticket_id: UUID) -> dict[str, object]:
    return {
        "type": "modal",
        "callback_id": "maint_cancel_ticket_submit",
        "private_metadata": _metadata(ticket_id),
        "title": {"type": "plain_text", "text": "Cancel ticket"},
        "submit": {"type": "plain_text", "text": "Cancel ticket"},
        "close": {"type": "plain_text", "text": "Back"},
        "blocks": [_text_input("reason", "value", "Cancellation reason", multiline=True)],
    }


def duplicate_modal(ticket_id: UUID) -> dict[str, object]:
    return {
        "type": "modal",
        "callback_id": "maint_duplicate_ticket_submit",
        "private_metadata": _metadata(ticket_id),
        "title": {"type": "plain_text", "text": "Mark duplicate"},
        "submit": {"type": "plain_text", "text": "Mark duplicate"},
        "close": {"type": "plain_text", "text": "Back"},
        "blocks": [
            _text_input("canonical", "value", "Canonical ticket number"),
            {**_text_input("reason", "value", "Reason", multiline=True), "optional": True},
        ],
    }
