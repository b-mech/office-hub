from __future__ import annotations

from app.core.config import settings


TEMPLATES = {
    "tenant_intake_confirm": (
        "{brand}: We received your maintenance request for {unit}. We'll be in touch soon. "
        "Reply to this number anytime with updates or photos."
    ),
    "tenant_triaged": "{brand}: Your maintenance request has been reviewed. Expected response: {timeframe}.",
    "tenant_scheduled": "{brand}: Your maintenance visit is scheduled for {window}. Reply if this doesn't work.",
    "tenant_entry_notice": (
        "{brand}: Notice of entry to {address}, {unit} on {weekday} {date} between "
        "{start_time} and {end_time} to {reason}. Reply with any questions."
    ),
    "tenant_consent_confirmation": (
        "{brand}: Confirming the visit you agreed to at {address}, {unit} on "
        "{weekday} {date}, {start_time}–{end_time}, to {reason}. Reply if this no longer works."
    ),
    "tenant_emergency_on_way": (
        "{brand}: A technician is on the way to {address}, {unit} for your emergency "
        "request. Reply or call {emergency_phone} if anything changes."
    ),
    "tenant_visit_cancelled": (
        "{brand}: The visit to {address}, {unit} scheduled for {weekday} {date} at "
        "{start_time} is no longer needed."
    ),
    "tenant_resolved_check": (
        "{brand}: We marked your maintenance request resolved. Reply YES if it's fixed, "
        "or tell us what's still wrong."
    ),
    "tenant_autoclosed": (
        "{brand}: Your maintenance request has been closed. Reply if the issue returns."
    ),
    "tenant_no_open_ticket": (
        "{brand}: Thanks for your message. To report a maintenance issue, tap here: {intake_url}"
    ),
    "vendor_offer": (
        "{brand}: work order {number} in {area}: {scope}.{entry_notes} Review and respond: {link}"
    ),
    "vendor_scheduled_confirm": "{brand}: work order {number} is confirmed for {window}.",
    "oncall_emergency_page": (
        "{brand}: emergency ticket {number} at {unit}. Open {link} now. "
        "Reply ACK to acknowledge."
    ),
}


def render_template(name: str, **values: object) -> str:
    try:
        text = TEMPLATES[name].format(brand=settings.public_brand_name, **values)
    except KeyError as exc:
        raise ValueError(f"Unknown or incomplete SMS template: {name}") from exc
    if name.startswith("tenant_"):
        return text
    signature = settings.sms_signature.strip()
    return f"{text} {signature}" if signature else text


def render_tenant_reply(body: str) -> str:
    """Apply the single tenant-facing brand prefix to a staff-written reply."""
    message = body.strip()
    prefix = f"{settings.public_brand_name}:"
    if message.casefold().startswith(prefix.casefold()):
        return message
    return f"{prefix} {message}"
