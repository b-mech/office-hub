from __future__ import annotations

from app.core.config import settings


TEMPLATES = {
    "tenant_intake_confirm": (
        "{brand}: we received your request {number} for {unit}. We'll be in touch soon. "
        "Reply to this number anytime with updates or photos."
    ),
    "tenant_triaged": "{brand}: {number} has been reviewed. Expected response: {timeframe}.",
    "tenant_scheduled": "{brand}: {number} is scheduled for {window}. Reply if this doesn't work.",
    "tenant_entry_notice": "{brand}: notice of entry for {unit} on {window}. {details}",
    "tenant_resolved_check": "{brand}: we marked {number} resolved. Reply YES if it's fixed, or tell us what's still wrong.",
    "tenant_autoclosed": "{brand}: {number} has been closed. Reply if the issue returns.",
    "tenant_no_open_ticket": "{brand}: we couldn't match this text to an open request. Report an issue here: {intake_url}",
    "vendor_offer": "{brand}: work order {number} in {area}: {scope}. Review and respond: {link}",
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
    signature = settings.sms_signature.strip()
    return f"{text} {signature}" if signature else text
