from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal
import json
from typing import Any, Callable
from uuid import UUID

from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.config import settings
from app.models.core import User
from app.models.maintenance import (
    MaintCategory,
    MaintParty,
    MaintPriority,
    MaintSlackCard,
    MaintStatus,
    MaintTicket,
    MaintVendor,
    MaintWorkOrder,
)
from app.services.maintenance.permissions import has_maintenance_permission
from app.services.maintenance.slack.dispatcher import ticket_card_view
from app.services.maintenance.slack.modals import (
    assignment_modal,
    cancel_modal,
    complete_work_order_modal,
    duplicate_modal,
    message_modal,
    resolve_modal,
    schedule_modal,
    triage_modal,
)
from app.services.maintenance.slack.outbox import enqueue_slack_notification
from app.services.maintenance.slack.relay import handle_edited_message, handle_thread_message
from app.services.maintenance.slack.render import render_cancel_button, render_ticket_card
from app.services.maintenance.slack.users import resolve_slack_user
from app.services.maintenance.sms.outbound import cancel_held_sms, queue_sms
from app.services.maintenance.state_machine import ActorContext, transition
from app.services.maintenance.tickets import (
    acknowledge_emergency,
    cancel_ticket,
    mark_duplicate,
    triage_ticket,
)
from app.services.maintenance.work_orders import (
    assign_vendor_work_order,
    complete_work_order,
    create_work_order,
    schedule_work_order,
)


def _action_value(body: Mapping[str, object]) -> str:
    actions = body.get("actions")
    if isinstance(actions, list) and actions and isinstance(actions[0], Mapping):
        return str(actions[0].get("value") or "")
    return ""


def _selected_action_value(body: Mapping[str, object]) -> str:
    actions = body.get("actions")
    if isinstance(actions, list) and actions and isinstance(actions[0], Mapping):
        selected = actions[0].get("selected_option")
        if isinstance(selected, Mapping):
            return str(selected.get("value") or "")
    return ""


def _metadata(body: Mapping[str, object]) -> dict[str, str]:
    view = body.get("view")
    if not isinstance(view, Mapping):
        return {}
    try:
        return {str(key): str(value) for key, value in json.loads(str(view.get("private_metadata") or "{}")).items()}
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}


def _state_value(body: Mapping[str, object], block: str) -> object:
    view = body.get("view")
    state = view.get("state") if isinstance(view, Mapping) else None
    values = state.get("values") if isinstance(state, Mapping) else None
    block_value = values.get(block) if isinstance(values, Mapping) else None
    action = block_value.get("value") if isinstance(block_value, Mapping) else None
    if not isinstance(action, Mapping):
        return None
    if "value" in action:
        return action.get("value")
    if "selected_option" in action and isinstance(action["selected_option"], Mapping):
        return action["selected_option"].get("value")
    if "selected_options" in action:
        return action.get("selected_options")
    return None


class SlackController:
    def __init__(self, session_factory: Callable[..., Any] = AsyncSessionLocal) -> None:
        self.session_factory = session_factory

    async def _actor(self, db: Any, client: Any, body: Mapping[str, object], action: str) -> tuple[User, ActorContext]:
        slack_user = body.get("user")
        slack_id = str(slack_user.get("id") or "") if isinstance(slack_user, Mapping) else ""
        slack_id = slack_id or str(body.get("user_id") or "")
        user = await resolve_slack_user(db, client, slack_id)
        if user is None or not has_maintenance_permission(user, action):
            raise PermissionError("Maintenance permission required")
        return user, ActorContext(
            MaintParty.STAFF,
            user_id=user.id,
            is_admin=has_maintenance_permission(user, "admin"),
        )

    async def message_event(self, event: Mapping[str, object], client: Any) -> None:
        async with self.session_factory() as db:
            if event.get("subtype") == "message_changed":
                await handle_edited_message(db, client, event)
            else:
                await handle_thread_message(db, client, event)
            await db.commit()

    async def ticket_command(self, body: Mapping[str, object], client: Any) -> None:
        number = str(body.get("text") or "").strip().upper()
        async with self.session_factory() as db:
            await self._actor(db, client, body, "view")
            ticket = await db.scalar(select(MaintTicket).where(MaintTicket.number == number))
            if ticket is None:
                await client.chat_postEphemeral(
                    channel=body["channel_id"], user=body["user_id"], text="Ticket not found."
                )
                return
            view = await ticket_card_view(db, ticket.id)
            await client.chat_postEphemeral(
                channel=body["channel_id"],
                user=body["user_id"],
                text=f"{view.number}: {view.title}",
                blocks=render_ticket_card(view),
            )

    async def tickets_command(self, body: Mapping[str, object], client: Any) -> None:
        async with self.session_factory() as db:
            await self._actor(db, client, body, "view")
            tickets = list(
                (
                    await db.scalars(
                        select(MaintTicket)
                        .where(
                            MaintTicket.status.notin_(
                                [MaintStatus.CLOSED, MaintStatus.CANCELLED, MaintStatus.DUPLICATE]
                            )
                        )
                        .order_by(MaintTicket.updated_at.desc())
                        .limit(20)
                    )
                ).all()
            )
            text = "\n".join(
                f"• *{ticket.number}* · {ticket.title} · {MaintStatus(ticket.status).value}"
                for ticket in tickets
            ) or "No open maintenance tickets."
            await client.chat_postEphemeral(
                channel=body["channel_id"], user=body["user_id"], text=text
            )

    async def acknowledge(self, body: Mapping[str, object], client: Any) -> None:
        ticket_id = UUID(_action_value(body))
        async with self.session_factory() as db:
            _, actor = await self._actor(db, client, body, "triage")
            ticket = await db.scalar(
                select(MaintTicket).where(MaintTicket.id == ticket_id).with_for_update()
            )
            if ticket is None:
                return
            await acknowledge_emergency(db, ticket, actor)
            await enqueue_slack_notification(
                db,
                idempotency_key=f"ticket:{ticket.id}:ack:{ticket.emergency_acked_at.isoformat()}",
                kind="ticket_updated",
                ticket_id=ticket.id,
            )
            await db.commit()
        channel = body.get("channel")
        message = body.get("message")
        if (
            isinstance(channel, Mapping)
            and isinstance(message, Mapping)
            and channel.get("id") == settings.slack_emergency_channel_id
        ):
            await client.chat_update(
                channel=channel.get("id"),
                ts=message.get("ts"),
                text="Emergency acknowledged; follow the ticket in #privi-tickets.",
            )

    async def cancel_sms(self, body: Mapping[str, object], client: Any) -> None:
        message_id = UUID(_action_value(body))
        async with self.session_factory() as db:
            user, actor = await self._actor(db, client, body, "message_external")
            message = await cancel_held_sms(db, message_id, actor)
            await enqueue_slack_notification(
                db,
                idempotency_key=f"sms:{message.id}:status:cancelled",
                kind="sms_status_changed",
                ticket_id=message.ticket_id,
                work_order_id=message.work_order_id,
                sms_message_id=message.id,
                payload={"status": "cancelled"},
            )
            await db.commit()
        await client.chat_postEphemeral(
            channel=message.slack_channel_id,
            user=str(user.slack_user_id),
            text="SMS cancelled before sending.",
        )

    async def reopen(self, body: Mapping[str, object], client: Any) -> None:
        ticket_id = UUID(_action_value(body))
        async with self.session_factory() as db:
            _, actor = await self._actor(db, client, body, "admin")
            ticket = await db.scalar(
                select(MaintTicket).where(MaintTicket.id == ticket_id).with_for_update()
            )
            if ticket:
                await transition(db, ticket, MaintStatus.IN_PROGRESS, actor, "Reopened from Slack")
                await enqueue_slack_notification(
                    db,
                    idempotency_key=f"ticket:{ticket.id}:reopened:{ticket.updated_at.isoformat()}",
                    kind="ticket_updated",
                    ticket_id=ticket.id,
                )
                await db.commit()

    async def open_modal(self, body: Mapping[str, object], client: Any, kind: str) -> None:
        value = _action_value(body)
        data = json.loads(value) if value.startswith("{") else {"id": value}
        ticket_id = UUID(str(data["id"]))
        async with self.session_factory() as db:
            action = (
                "assign"
                if kind in {"assign", "schedule", "complete"}
                else "message_external"
                if kind == "message"
                else "triage"
            )
            await self._actor(db, client, body, action)
            ticket = await db.get(MaintTicket, ticket_id)
            if ticket is None:
                return
            if kind == "triage":
                modal = triage_modal(ticket.id, ticket.title)
            elif kind == "message":
                modal = message_modal(ticket.id)
            elif kind == "resolve":
                modal = resolve_modal(ticket.id)
            elif kind == "schedule":
                modal = schedule_modal(ticket.id, UUID(str(data["work_order_id"])))
            elif kind == "complete":
                modal = complete_work_order_modal(ticket.id, UUID(str(data["work_order_id"])))
            elif kind == "cancel":
                modal = cancel_modal(ticket.id)
            elif kind == "duplicate":
                modal = duplicate_modal(ticket.id)
            else:
                vendors = list((await db.scalars(select(MaintVendor).where(MaintVendor.is_active.is_(True)).order_by(MaintVendor.name))).all())
                staff = list((await db.scalars(select(User).where(User.is_active.is_(True)).order_by(User.full_name))).all())
                options = [
                    {"text": {"type": "plain_text", "text": f"Vendor · {item.name}"}, "value": f"vendor:{item.id}"}
                    for item in vendors
                ] + [
                    {"text": {"type": "plain_text", "text": f"Staff · {item.full_name}"}, "value": f"staff:{item.id}"}
                    for item in staff
                ]
                modal = assignment_modal(ticket.id, options)
        await client.views_open(trigger_id=body["trigger_id"], view=modal)

    async def submit_triage(self, body: Mapping[str, object], client: Any) -> None:
        ticket_id = UUID(_metadata(body)["ticket_id"])
        async with self.session_factory() as db:
            _, actor = await self._actor(db, client, body, "triage")
            ticket = await db.scalar(select(MaintTicket).where(MaintTicket.id == ticket_id).with_for_update())
            if ticket:
                was_emergency = ticket.is_emergency
                await triage_ticket(
                    db,
                    ticket,
                    actor,
                    category=MaintCategory(str(_state_value(body, "category"))),
                    priority=MaintPriority(str(_state_value(body, "priority"))),
                    is_emergency=bool(_state_value(body, "emergency")),
                    title=str(_state_value(body, "title") or ""),
                    staff_summary=str(_state_value(body, "summary") or "") or None,
                )
                await self._enqueue_ticket_update(db, ticket)
                if ticket.is_emergency and not was_emergency:
                    await enqueue_slack_notification(
                        db,
                        idempotency_key=f"ticket:{ticket.id}:emergency:{ticket.updated_at.isoformat()}",
                        kind="emergency_alert",
                        ticket_id=ticket.id,
                    )
                await db.commit()

    async def submit_message(self, body: Mapping[str, object], client: Any) -> None:
        ticket_id = UUID(_metadata(body)["ticket_id"])
        async with self.session_factory() as db:
            _, actor = await self._actor(db, client, body, "message_external")
            ticket = await db.get(MaintTicket, ticket_id)
            if ticket is None or not ticket.reporter_phone_e164:
                raise ValueError("Ticket has no reporter phone")
            message = await queue_sms(
                db,
                to=ticket.reporter_phone_e164,
                body=str(_state_value(body, "message") or ""),
                ticket_id=ticket.id,
                automated=False,
                actor_party=actor.party,
            )
            await db.commit()
        await client.chat_postEphemeral(
            channel=settings.slack_tickets_channel_id,
            user=body["user"]["id"],
            text="SMS held briefly before sending.",
            blocks=render_cancel_button(message.id),
        )

    async def submit_resolve(self, body: Mapping[str, object], client: Any) -> None:
        ticket_id = UUID(_metadata(body)["ticket_id"])
        async with self.session_factory() as db:
            _, actor = await self._actor(db, client, body, "triage")
            ticket = await db.scalar(select(MaintTicket).where(MaintTicket.id == ticket_id).with_for_update())
            if ticket:
                await transition(
                    db,
                    ticket,
                    MaintStatus.RESOLVED,
                    actor,
                    str(_state_value(body, "reason") or ""),
                )
                await self._enqueue_ticket_update(db, ticket)
                await db.commit()

    async def submit_assign(self, body: Mapping[str, object], client: Any) -> None:
        ticket_id = UUID(_metadata(body)["ticket_id"])
        assignee_type, raw_id = str(_state_value(body, "assignee")).split(":", 1)
        estimate = str(_state_value(body, "estimate") or "").strip()
        async with self.session_factory() as db:
            _, actor = await self._actor(db, client, body, "assign")
            ticket = await db.scalar(select(MaintTicket).where(MaintTicket.id == ticket_id).with_for_update())
            if ticket is None:
                return
            if assignee_type == "vendor":
                order = await assign_vendor_work_order(
                    db,
                    ticket,
                    actor,
                    vendor_id=UUID(raw_id),
                    scope=str(_state_value(body, "scope") or ""),
                    cost_estimate=Decimal(estimate) if estimate else None,
                )
            else:
                order, _ = await create_work_order(
                    db,
                    ticket,
                    actor,
                    assignee_type="staff",
                    assignee_user_id=UUID(raw_id),
                    scope=str(_state_value(body, "scope") or ""),
                    cost_estimate=Decimal(estimate) if estimate else None,
                )
            await enqueue_slack_notification(
                db,
                idempotency_key=f"work-order:{order.id}:created",
                kind="work_order_created",
                ticket_id=ticket.id,
                work_order_id=order.id,
            )
            await self._enqueue_ticket_update(db, ticket)
            await db.commit()

    async def submit_schedule(self, body: Mapping[str, object], client: Any) -> None:
        data = _metadata(body)
        async with self.session_factory() as db:
            _, actor = await self._actor(db, client, body, "assign")
            ticket = await db.scalar(select(MaintTicket).where(MaintTicket.id == UUID(data["ticket_id"])).with_for_update())
            order = await db.get(MaintWorkOrder, UUID(data["work_order_id"]))
            if ticket and order:
                await schedule_work_order(
                    db,
                    ticket,
                    order,
                    actor,
                    datetime.fromisoformat(str(_state_value(body, "start"))),
                    datetime.fromisoformat(str(_state_value(body, "end"))),
                    admin_override_reason=str(_state_value(body, "override") or "") or None,
                )
                await enqueue_slack_notification(
                    db,
                    idempotency_key=f"work-order:{order.id}:scheduled:{order.scheduled_start.isoformat()}",
                    kind="work_order_created",
                    ticket_id=ticket.id,
                    work_order_id=order.id,
                )
                await self._enqueue_ticket_update(db, ticket)
                await db.commit()

    async def submit_complete(self, body: Mapping[str, object], client: Any) -> None:
        data = _metadata(body)
        async with self.session_factory() as db:
            _, actor = await self._actor(db, client, body, "assign")
            ticket = await db.scalar(select(MaintTicket).where(MaintTicket.id == UUID(data["ticket_id"])).with_for_update())
            order = await db.get(MaintWorkOrder, UUID(data["work_order_id"]))
            if ticket is None or order is None:
                return
            raw_cost = str(_state_value(body, "cost") or "").strip()
            all_complete = await complete_work_order(
                db,
                ticket,
                order,
                actor,
                completion_notes=str(_state_value(body, "notes") or ""),
                cost_actual=Decimal(raw_cost) if raw_cost else None,
            )
            await enqueue_slack_notification(
                db,
                idempotency_key=f"work-order:{order.id}:completed:{order.completed_at.isoformat()}",
                kind="work_order_created",
                ticket_id=ticket.id,
                work_order_id=order.id,
            )
            await self._enqueue_ticket_update(db, ticket)
            card = await db.scalar(select(MaintSlackCard).where(MaintSlackCard.work_order_id == order.id))
            await db.commit()
        if all_complete and card:
            await client.chat_postMessage(
                channel=card.channel_id,
                thread_ts=card.message_ts,
                text="All active work orders are complete. Mark the ticket resolved?",
                blocks=[
                    {
                        "type": "actions",
                        "elements": [
                            {
                                "type": "button",
                                "text": {"type": "plain_text", "text": "Mark resolved"},
                                "style": "primary",
                                "action_id": "maint_mark_resolved",
                                "value": str(ticket.id),
                            }
                        ],
                    }
                ],
            )

    async def mark_resolved(self, body: Mapping[str, object], client: Any) -> None:
        ticket_id = UUID(_action_value(body))
        async with self.session_factory() as db:
            _, actor = await self._actor(db, client, body, "triage")
            ticket = await db.scalar(select(MaintTicket).where(MaintTicket.id == ticket_id).with_for_update())
            if ticket:
                await transition(db, ticket, MaintStatus.RESOLVED, actor, "All work orders completed")
                await self._enqueue_ticket_update(db, ticket)
                await db.commit()

    async def submit_cancel(self, body: Mapping[str, object], client: Any) -> None:
        ticket_id = UUID(_metadata(body)["ticket_id"])
        async with self.session_factory() as db:
            _, actor = await self._actor(db, client, body, "triage")
            ticket = await db.scalar(select(MaintTicket).where(MaintTicket.id == ticket_id).with_for_update())
            if ticket:
                await cancel_ticket(
                    db,
                    ticket,
                    actor,
                    reason=str(_state_value(body, "reason") or ""),
                )
                await self._enqueue_ticket_update(db, ticket)
                await db.commit()

    async def submit_duplicate(self, body: Mapping[str, object], client: Any) -> None:
        ticket_id = UUID(_metadata(body)["ticket_id"])
        canonical_number = str(_state_value(body, "canonical") or "").strip().upper()
        async with self.session_factory() as db:
            _, actor = await self._actor(db, client, body, "triage")
            ticket = await db.scalar(select(MaintTicket).where(MaintTicket.id == ticket_id).with_for_update())
            canonical = await db.scalar(select(MaintTicket).where(MaintTicket.number == canonical_number))
            if ticket is None or canonical is None:
                raise ValueError("Canonical ticket was not found")
            await mark_duplicate(
                db,
                ticket,
                canonical,
                actor,
                reason=str(_state_value(body, "reason") or "") or None,
            )
            await self._enqueue_ticket_update(db, ticket)
            await db.commit()

    async def _enqueue_ticket_update(self, db: Any, ticket: MaintTicket) -> None:
        await enqueue_slack_notification(
            db,
            idempotency_key=f"ticket:{ticket.id}:updated:{ticket.updated_at.isoformat()}",
            kind="ticket_updated",
            ticket_id=ticket.id,
        )


def register_handlers(app: Any, controller: SlackController) -> None:
    @app.event("message")
    async def message_event(event: Mapping[str, object], client: Any) -> None:
        await controller.message_event(event, client)

    @app.command("/ticket")
    async def ticket_command(ack: Any, body: Mapping[str, object], client: Any) -> None:
        await ack()
        await controller.ticket_command(body, client)

    @app.command("/tickets")
    async def tickets_command(ack: Any, body: Mapping[str, object], client: Any) -> None:
        await ack()
        await controller.tickets_command(body, client)

    action_handlers = {
        "maint_ack_emergency": controller.acknowledge,
        "maint_cancel_held_sms": controller.cancel_sms,
        "maint_reopen": controller.reopen,
        "maint_mark_resolved": controller.mark_resolved,
    }
    for action_id, handler in action_handlers.items():
        app.action(action_id)(_action_wrapper(handler))

    for action_id, kind in {
        "maint_open_triage": "triage",
        "maint_open_assign": "assign",
        "maint_open_message": "message",
        "maint_open_resolve": "resolve",
        "maint_open_schedule": "schedule",
        "maint_open_complete_work_order": "complete",
    }.items():
        app.action(action_id)(_modal_wrapper(controller, kind))
    app.action("maint_more")(_more_wrapper(controller))

    for callback_id, handler in {
        "maint_triage_submit": controller.submit_triage,
        "maint_assign_submit": controller.submit_assign,
        "maint_message_submit": controller.submit_message,
        "maint_resolve_submit": controller.submit_resolve,
        "maint_schedule_submit": controller.submit_schedule,
        "maint_complete_work_order_submit": controller.submit_complete,
        "maint_cancel_ticket_submit": controller.submit_cancel,
        "maint_duplicate_ticket_submit": controller.submit_duplicate,
    }.items():
        app.view(callback_id)(_view_wrapper(handler))


def _action_wrapper(handler: Any) -> Any:
    async def wrapped(ack: Any, body: Mapping[str, object], client: Any) -> None:
        await ack()
        await handler(body, client)

    return wrapped


def _modal_wrapper(controller: SlackController, kind: str) -> Any:
    async def wrapped(ack: Any, body: Mapping[str, object], client: Any) -> None:
        await ack()
        await controller.open_modal(body, client, kind)

    return wrapped


def _view_wrapper(handler: Any) -> Any:
    async def wrapped(ack: Any, body: Mapping[str, object], client: Any) -> None:
        await ack()
        await handler(body, client)

    return wrapped


def _more_wrapper(controller: SlackController) -> Any:
    async def wrapped(ack: Any, body: Mapping[str, object], client: Any) -> None:
        await ack()
        raw = _selected_action_value(body)
        data = json.loads(raw)
        action_body = dict(body)
        action_body["actions"] = [{"value": raw}]
        await controller.open_modal(action_body, client, str(data["operation"]))

    return wrapped
    duplicate_modal,
