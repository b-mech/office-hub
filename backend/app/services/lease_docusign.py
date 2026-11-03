"""Lease envelope operations using the shared Change Orders JWT client."""
from __future__ import annotations

import base64
from typing import Any

from docusign_esign import DateSigned, Document, Envelope, EnvelopeDefinition, EnvelopesApi
from docusign_esign import List as ListTab
from docusign_esign import ListItem, Recipients, SignHere, Signer, Tabs, Text

from app.core.config import settings
from app.services.docusign import get_docusign_client


def _api() -> EnvelopesApi:
    client = get_docusign_client()
    if client is None:
        raise RuntimeError("DocuSign is not configured")
    return EnvelopesApi(client)


def _anchor(name: str, *, signature: bool = False) -> dict[str, Any]:
    return dict(anchor_string=f"\\{name}\\", anchor_ignore_if_not_present=True,
                anchor_case_sensitive=True, anchor_match_whole_word=True, anchor_units="pixels",
                anchor_x_offset="0" if signature else "2",
                anchor_y_offset="-10" if signature else "-4")


def _tabs(signer: int, *, landlord: bool = False) -> Tabs:
    prefix = "ll" if landlord else f"t{signer}"
    sign = [SignHere(**_anchor(f"{prefix}_sig", signature=True))]
    dates = [DateSigned(**_anchor(f"{prefix}_date"))]
    texts: list[Text] = []
    lists: list[ListTab] = []
    if not landlord:
        for suffix, width in (("phone", 85), ("email", 154)):
            name = f"{prefix}_{suffix}"
            validation = ({"validation_pattern": r"^[^\s@]+@[^\s@]+\.[^\s@]+$",
                           "validation_message": "Enter a valid email address"} if suffix == "email" else {})
            texts.append(Text(**_anchor(name), tab_label=name, required=True, width=width, **validation))
        name = f"{prefix}_pref"
        lists.append(ListTab(**_anchor(name), tab_label=name, required=True, width=85,
                             list_items=[ListItem(text=x, value=x) for x in ("Phone", "Text", "Email")]))
        if signer == 1:
            for grid, rows, widths in (("oc", 4, [120, 85, 55, 75, 119]),
                                       ("ec", 2, [140, 90, 90, 144]),
                                       ("vh", 2, [140, 80, 90, 154]),
                                       ("pt", 2, [140, 80, 90, 154])):
                for row in range(1, rows + 1):
                    for col, width in enumerate(widths, 1):
                        name = f"{grid}_r{row}_c{col}"
                        required = grid == "ec" and row == 1 and col in (1, 3)
                        texts.append(Text(**_anchor(name), tab_label=name, required=required, width=width))
    return Tabs(sign_here_tabs=sign, date_signed_tabs=dates, text_tabs=texts, list_tabs=lists)


def send(pdf: bytes, context: dict[str, Any]) -> str:
    address = context["unit_address"]
    landlord_email = settings.lease_landlord_signer_email.strip()
    if not landlord_email:
        raise RuntimeError("LEASE_LANDLORD_SIGNER_EMAIL must be configured")
    if settings.environment.casefold() not in {"production", "prod"}:
        allowed = settings.lease_nonproduction_signer_email.strip()
        if not allowed or landlord_email.casefold() != allowed.casefold():
            raise RuntimeError("Non-production lease signer must match LEASE_NONPRODUCTION_SIGNER_EMAIL")
    signers = [Signer(email=landlord_email, name=settings.lease_landlord_signer_name,
                      recipient_id="1", routing_order="1", tabs=_tabs(0, landlord=True))]
    for index, tenant in enumerate(context["tenants"], 1):
        signers.append(Signer(email=tenant["email"], name=tenant["name"], recipient_id=str(index + 1),
                              routing_order="2", tabs=_tabs(index)))
    envelope = EnvelopeDefinition(
        email_subject=f"Residential Tenancy Agreement – {address}",
        email_blurb="Please review the lease, complete the contact form, and sign the agreement and Rules of Care.",
        documents=[Document(document_base64=base64.b64encode(pdf).decode("ascii"),
                            name=f"Residential Tenancy Agreement – {address}.pdf", file_extension="pdf", document_id="1")],
        recipients=Recipients(signers=signers), status="sent")
    result = _api().create_envelope(account_id=settings.docusign_account_id, envelope_definition=envelope)
    if not result.envelope_id:
        raise RuntimeError("DocuSign did not return an envelope ID")
    return str(result.envelope_id)


def status(envelope_id: str) -> tuple[str, dict[str, str]]:
    api = _api()
    envelope = api.get_envelope(settings.docusign_account_id, envelope_id)
    recipients = api.list_recipients(settings.docusign_account_id, envelope_id)
    signer_status = {str(s.recipient_id): str(s.status or "") for s in (recipients.signers or [])}
    return str(envelope.status or "").lower(), signer_status


def void(envelope_id: str, reason: str) -> None:
    _api().update(settings.docusign_account_id, envelope_id,
                  envelope=Envelope(status="voided", voided_reason=reason))


def resend(envelope_id: str) -> None:
    recipients = _api().list_recipients(settings.docusign_account_id, envelope_id)
    _api().update_recipients(settings.docusign_account_id, envelope_id,
                             recipients=recipients, resend_envelope="true")


def certificate(envelope_id: str) -> bytes:
    document = _api().get_document(settings.docusign_account_id, "certificate", envelope_id)
    if isinstance(document, bytes):
        return document
    with open(document, "rb") as file:
        return file.read()


def form_data(envelope_id: str) -> dict[str, str]:
    result = _api().get_form_data(settings.docusign_account_id, envelope_id)
    return {field.name: field.value for field in (result.form_data or []) if field.name}


def structured_contacts(values: dict[str, str], context: dict[str, Any]) -> dict[str, Any]:
    tenants = [{"name": tenant["name"], "phone": values.get(f"t{i}_phone"),
                "email": values.get(f"t{i}_email"), "preferred": values.get(f"t{i}_pref")}
               for i, tenant in enumerate(context["tenants"], 1)]
    def grid(prefix: str, rows: int, fields: tuple[str, ...]) -> list[dict[str, str]]:
        items = []
        for row in range(1, rows + 1):
            item = {field: values.get(f"{prefix}_r{row}_c{col}", "") for col, field in enumerate(fields, 1)}
            if any(item.values()):
                items.append(item)
        return items
    return {"raw": values, "tenants": tenants,
            "occupants": grid("oc", 4, ("name", "relationship", "adult_child", "phone", "email")),
            "emergency_contacts": grid("ec", 2, ("name", "relationship", "phone", "email")),
            "vehicles": grid("vh", 2, ("make_model", "colour", "licence_plate", "owner_driver")),
            "pets": grid("pt", 2, ("type_breed", "name", "approx_weight", "notes"))}
