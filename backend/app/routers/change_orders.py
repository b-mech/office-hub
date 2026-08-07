from __future__ import annotations

import asyncio
import base64
from datetime import date
from datetime import datetime
from datetime import timezone
from decimal import Decimal
import hashlib
import hmac
import logging
from typing import Any
from typing import Annotated
from typing import Literal
from uuid import UUID
from xml.etree import ElementTree

from fastapi import APIRouter
from fastapi import BackgroundTasks
from fastapi import Depends
from fastapi import Header
from fastapi import HTTPException
from fastapi import Request
from fastapi import Query
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from pydantic import BaseModel
from pydantic import EmailStr
from pydantic import Field
from pydantic import TypeAdapter
from pydantic import ValidationError

from app.core.config import settings
from app.core.database import get_db
from app.core.database import AsyncSessionLocal
from app.models.sales import ChangeOrder as ChangeOrderModel
from app.models.sales import ChangeOrderLineItem as ChangeOrderLineItemModel
from app.models.sales import ChangeOrderStatus
from app.services.box import file_change_order_pdf
from app.services.change_orders.pdf import render_change_order_pdf
from app.services.docusign import get_signed_pdf
from app.services.change_order_payments import send_payment_email
from app.services.change_order_payments import send_to_docusign
from app.services.change_order_payments import prepare_for_signature
from app.services.change_order_payments import save_payment_link_and_send
from app.services import quickbooks
from app.services.extraction.claude_provider import ClaudeProvider


logger = logging.getLogger(__name__)


def verify_api_key(x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None) -> None:
    if x_api_key != settings.office_hub_api_key:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


API_KEY_DEPENDENCIES = [Depends(verify_api_key)]


router = APIRouter(
    prefix="/change-orders",
    tags=["change-orders"],
)


class ChangeOrderExtractRequest(BaseModel):
    email_body: str = Field(min_length=1)


class ChangeOrderLineItem(BaseModel):
    description: str = ""
    amount: Decimal = Decimal("0")
    is_credit: bool = False


class ChangeOrderDraft(BaseModel):
    lot_id: UUID | None = None
    address: str = ""
    client_name: str = ""
    customer_email: str = ""
    co_number: str = ""
    date: str = ""
    line_items: list[ChangeOrderLineItem] = Field(default_factory=list)
    payment_method: Literal["add_to_mortgage", "due_upon_receipt"] = "due_upon_receipt"
    notes: str = ""


class ChangeOrderDraftResponse(BaseModel):
    id: str


class ChangeOrderOut(ChangeOrderDraft):
    id: UUID
    status: ChangeOrderStatus = "draft"
    subtotal: Decimal = Decimal("0")
    gst: Decimal = Decimal("0")
    total: Decimal = Decimal("0")
    docusign_envelope_id: str | None = None
    plooto_payment_link: str | None = None
    plooto_status: Literal["not_started", "awaiting_link", "link_received"] = "not_started"
    qb_invoice_id: str | None = None
    qb_invoice_status: Literal["not_created", "created", "synced_error", "paid"] = "not_created"
    qb_customer_id: str | None = None
    qb_project_id: str | None = None
    qb_sync_error: str | None = None
    payment_email_sent_at: datetime | None = None
    box_file_id: str | None = None
    box_file_url: str | None = None
    box_unfiled: bool = False
    archived_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class ChangeOrderSignatureResponse(BaseModel):
    id: UUID
    status: ChangeOrderStatus
    docusign_envelope_id: str | None = None
    box_file_id: str | None = None
    box_file_url: str | None = None
    box_unfiled: bool = False
    message: str


class ChangeOrderStatusRequest(BaseModel):
    status: ChangeOrderStatus


class ChangeOrderSignatureRequest(BaseModel):
    signer_email: str = ""
    signer_name: str = ""


class PlootoLinkRequest(BaseModel):
    plooto_payment_link: str = Field(min_length=1)


class QboMappingRequest(BaseModel):
    qb_customer_id: str = Field(min_length=1)
    qb_project_id: str = Field(min_length=1)


class ChangeOrderUpdate(BaseModel):
    address: str | None = None
    client_name: str | None = None
    customer_email: str | None = None
    line_items: list[ChangeOrderLineItem] | None = None
    notes: str | None = None


@router.post("/extract", response_model=ChangeOrderDraft, dependencies=API_KEY_DEPENDENCIES)
async def extract_change_order(request: ChangeOrderExtractRequest) -> ChangeOrderDraft:
    provider = ClaudeProvider()
    raw_response = await asyncio.to_thread(_request_change_order_extract, provider, request.email_body)
    parsed = provider._parse_json_response(raw_response)
    return _normalize_change_order_draft(parsed)


@router.post("/draft", response_model=ChangeOrderDraftResponse, dependencies=API_KEY_DEPENDENCIES)
async def save_change_order_draft(
    draft: ChangeOrderDraft,
    db: AsyncSession = Depends(get_db),
) -> ChangeOrderDraftResponse:
    subtotal, gst, total = _calculate_totals(draft.line_items)
    change_order = ChangeOrderModel(
        lot_id=draft.lot_id,
        address=draft.address.strip(),
        client_name=draft.client_name.strip(),
        customer_email=draft.customer_email.strip() or None,
        co_number=draft.co_number.strip() or None,
        date=_parse_date(draft.date),
        payment_method=draft.payment_method,
        notes=draft.notes.strip() or None,
        org_id=settings.default_org_id,
        subtotal=subtotal,
        gst=gst,
        total=total,
    )
    change_order.line_items = [
        ChangeOrderLineItemModel(
            description=item.description.strip(),
            amount=abs(item.amount),
            is_credit=item.is_credit,
            sort_order=index,
        )
        for index, item in enumerate(draft.line_items)
    ]

    async with db.begin():
        db.add(change_order)
        await db.flush()

    return ChangeOrderDraftResponse(id=str(change_order.id))


@router.get("", response_model=list[ChangeOrderOut], dependencies=API_KEY_DEPENDENCIES)
async def list_change_orders(
    include_archived: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
) -> list[ChangeOrderOut]:
    statement = (
        select(ChangeOrderModel)
        .where(ChangeOrderModel.org_id == settings.default_org_id)
        .options(selectinload(ChangeOrderModel.line_items))
        .order_by(ChangeOrderModel.created_at.desc())
    )
    if not include_archived:
        statement = statement.where(ChangeOrderModel.archived_at.is_(None))
    result = await db.execute(statement)
    return [_change_order_out(change_order) for change_order in result.scalars()]


@router.post("/webhook/docusign")
async def docusign_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    raw_body = await request.body()
    if not _valid_docusign_signature(raw_body, request.headers.get("X-DocuSign-Signature-1")):
        logger.warning("Rejected DocuSign webhook with invalid HMAC signature")
        raise HTTPException(status_code=401, detail="Invalid DocuSign signature")

    envelope_id, envelope_status = _parse_docusign_webhook(raw_body)
    logger.info("Received DocuSign webhook envelope_id=%s status=%s", envelope_id, envelope_status)
    if not envelope_id:
        return {"status": "ignored"}
    if envelope_status.lower() != "completed":
        return {"status": "ignored"}

    result = await db.execute(
        select(ChangeOrderModel)
        .where(ChangeOrderModel.docusign_envelope_id == envelope_id)
        .options(selectinload(ChangeOrderModel.line_items))
    )
    change_order = result.scalar_one_or_none()
    if change_order is None:
        logger.info("No change order found for DocuSign envelope %s", envelope_id)
        return {"status": "ignored"}

    change_order.status = "signed"
    await db.commit()
    try:
        signed_pdf = await asyncio.to_thread(get_signed_pdf, envelope_id)
        if signed_pdf:
            box_file_id, box_file_url, box_unfiled = await asyncio.to_thread(file_change_order_pdf, address=change_order.address, pdf_bytes=signed_pdf, signed=True)
            if box_file_id:
                change_order.box_file_id, change_order.box_file_url, change_order.box_unfiled = box_file_id, box_file_url, box_unfiled
                await db.commit()
        else:
            logger.warning("No signed PDF returned for DocuSign envelope %s", envelope_id)
    except Exception:
        logger.exception("Signed change order %s Box filing failed", change_order.id)
    try:
        await send_payment_email(db, change_order)
    except Exception:
        logger.exception("Signed change order %s payment email failed", change_order.id)
    return {"status": "ok"}


@router.get("/{change_order_id}", response_model=ChangeOrderOut, dependencies=API_KEY_DEPENDENCIES)
async def get_change_order(
    change_order_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> ChangeOrderOut:
    result = await db.execute(
        select(ChangeOrderModel)
        .where(
            ChangeOrderModel.id == change_order_id,
            ChangeOrderModel.org_id == settings.default_org_id,
        )
        .options(selectinload(ChangeOrderModel.line_items))
    )
    change_order = result.scalar_one_or_none()
    if not change_order:
        raise HTTPException(status_code=404, detail="Change order not found")
    return _change_order_out(change_order)


@router.patch("/{change_order_id}", response_model=ChangeOrderOut, dependencies=API_KEY_DEPENDENCIES)
async def update_change_order(
    change_order_id: UUID,
    request: ChangeOrderUpdate,
    db: AsyncSession = Depends(get_db),
) -> ChangeOrderOut:
    change_order = await _get_change_order_model(change_order_id=change_order_id, db=db)
    if change_order.archived_at is not None:
        raise HTTPException(status_code=409, detail="Archived change orders cannot be edited.")
    if change_order.status in {"signed", "complete"}:
        raise HTTPException(status_code=409, detail="Signed or complete change orders are immutable.")

    updates = request.model_dump(exclude_unset=True)
    if change_order.status == "sent" and "line_items" in updates:
        if _line_items_changed(change_order.line_items, request.line_items or []):
            raise HTTPException(
                status_code=409,
                detail="Sent change orders cannot have line items or amounts edited. Void and resend instead.",
            )

    if request.address is not None:
        change_order.address = request.address.strip()
    if request.client_name is not None:
        change_order.client_name = request.client_name.strip()
    if request.customer_email is not None:
        email = request.customer_email.strip()
        if email:
            _validate_email(email)
        change_order.customer_email = email or None
    if request.notes is not None:
        change_order.notes = request.notes.strip() or None
    if request.line_items is not None and change_order.status == "draft":
        subtotal, gst, total = _calculate_totals(request.line_items)
        change_order.subtotal = subtotal
        change_order.gst = gst
        change_order.total = total
        change_order.line_items = [
            ChangeOrderLineItemModel(
                description=item.description.strip(),
                amount=abs(item.amount),
                is_credit=item.is_credit,
                sort_order=index,
            )
            for index, item in enumerate(request.line_items)
        ]

    await db.commit()
    await db.refresh(change_order)
    return _change_order_out(change_order)


@router.get("/{change_order_id}/pdf", dependencies=API_KEY_DEPENDENCIES)
async def get_change_order_pdf(
    change_order_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> Response:
    change_order = await _get_change_order_model(change_order_id=change_order_id, db=db)
    pdf_bytes = render_change_order_pdf(change_order)
    box_file_id, box_file_url, box_unfiled = file_change_order_pdf(
        address=change_order.address,
        pdf_bytes=pdf_bytes,
        signed=False,
    )
    if box_file_id:
        change_order.box_file_id = box_file_id
        change_order.box_file_url = box_file_url
        change_order.box_unfiled = box_unfiled
        if box_unfiled:
            logger.warning("Unsigned change order %s filed to Unfiled Change Orders", change_order.id)
        await db.commit()
    filename = _change_order_filename(change_order)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@router.patch("/{change_order_id}/status", response_model=ChangeOrderOut, dependencies=API_KEY_DEPENDENCIES)
async def update_change_order_status(
    change_order_id: UUID,
    request: ChangeOrderStatusRequest,
    db: AsyncSession = Depends(get_db),
) -> ChangeOrderOut:
    change_order = await _get_change_order_model(change_order_id=change_order_id, db=db)
    change_order.status = request.status
    await db.commit()
    return _change_order_out(change_order)


@router.delete("/{change_order_id}", response_model=ChangeOrderOut, dependencies=API_KEY_DEPENDENCIES)
async def archive_change_order(
    change_order_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> ChangeOrderOut:
    change_order = await _get_change_order_model(change_order_id=change_order_id, db=db)
    if change_order.archived_at is None:
        change_order.archived_at = datetime.now(tz=timezone.utc)
        await db.commit()
        await db.refresh(change_order)
    return _change_order_out(change_order)


@router.post("/{change_order_id}/send-signature", response_model=ChangeOrderSignatureResponse, dependencies=API_KEY_DEPENDENCIES)
async def send_change_order_for_signature(
    change_order_id: UUID,
    request: ChangeOrderSignatureRequest,
    db: AsyncSession = Depends(get_db),
) -> ChangeOrderSignatureResponse:
    change_order = await _get_change_order_model(change_order_id=change_order_id, db=db)
    try:
        envelope_id = await send_to_docusign(db, change_order, signer_name=request.signer_name)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return ChangeOrderSignatureResponse(
        id=change_order.id,
        status=change_order.status,
        docusign_envelope_id=change_order.docusign_envelope_id,
        box_file_id=change_order.box_file_id,
        box_file_url=change_order.box_file_url,
        box_unfiled=change_order.box_unfiled,
        message=(
            "Change order sent to DocuSign for signature."
        ),
    )


async def _create_qbo_invoice_background(change_order_id: UUID) -> None:
    async with AsyncSessionLocal() as db:
        await quickbooks.create_invoice(db, change_order_id)


@router.post("/{change_order_id}/prepare-signature", response_model=ChangeOrderOut, dependencies=API_KEY_DEPENDENCIES)
async def prepare_change_order_signature(change_order_id: UUID, background_tasks: BackgroundTasks, db: AsyncSession = Depends(get_db)) -> ChangeOrderOut:
    change_order = await _get_change_order_model(change_order_id=change_order_id, db=db)
    try:
        await prepare_for_signature(db, change_order)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    background_tasks.add_task(_create_qbo_invoice_background, change_order.id)
    return _change_order_out(change_order)


@router.post("/{change_order_id}/payment-link", response_model=ChangeOrderSignatureResponse, dependencies=API_KEY_DEPENDENCIES)
async def submit_change_order_payment_link(change_order_id: UUID, request: PlootoLinkRequest, db: AsyncSession = Depends(get_db)) -> ChangeOrderSignatureResponse:
    change_order = await _get_change_order_model(change_order_id=change_order_id, db=db)
    try:
        envelope_id = await save_payment_link_and_send(db, change_order, request.plooto_payment_link)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return ChangeOrderSignatureResponse(id=change_order.id, status=change_order.status, docusign_envelope_id=envelope_id, box_file_id=change_order.box_file_id, box_file_url=change_order.box_file_url, box_unfiled=change_order.box_unfiled, message="Plooto link saved and change order sent to DocuSign.")


@router.post("/{change_order_id}/qbo/retry", response_model=ChangeOrderOut, dependencies=API_KEY_DEPENDENCIES)
async def retry_change_order_qbo(change_order_id: UUID, db: AsyncSession = Depends(get_db)) -> ChangeOrderOut:
    change_order = await _get_change_order_model(change_order_id=change_order_id, db=db)
    await quickbooks.retry_invoice(db, change_order)
    return _change_order_out(change_order)


@router.post("/{change_order_id}/qbo/mapping", response_model=ChangeOrderOut, dependencies=API_KEY_DEPENDENCIES)
async def set_change_order_qbo_mapping(change_order_id: UUID, request: QboMappingRequest, db: AsyncSession = Depends(get_db)) -> ChangeOrderOut:
    change_order = await _get_change_order_model(change_order_id=change_order_id, db=db)
    await quickbooks.set_mapping_and_retry(db, change_order, request.qb_customer_id, request.qb_project_id)
    return _change_order_out(change_order)


@router.get("/qbo/oauth/start", dependencies=API_KEY_DEPENDENCIES)
async def qbo_oauth_start() -> dict[str, str]:
    try:
        return {"auth_url": quickbooks.authorization_url()}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/qbo/oauth/callback")
async def qbo_oauth_callback(code: str, state: str, realmId: str) -> dict[str, str]:
    try:
        await quickbooks.handle_callback(code, state, realmId)
        return {"status": "connected"}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{change_order_id}/sync-signed", response_model=ChangeOrderSignatureResponse, dependencies=API_KEY_DEPENDENCIES)
async def sync_signed_change_order(
    change_order_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> ChangeOrderSignatureResponse:
    change_order = await _get_change_order_model(change_order_id=change_order_id, db=db)
    if not change_order.docusign_envelope_id:
        raise HTTPException(status_code=400, detail="Change order has not been sent to DocuSign.")

    signed_pdf = await asyncio.to_thread(get_signed_pdf, change_order.docusign_envelope_id)

    if signed_pdf is None:
        return ChangeOrderSignatureResponse(
            id=change_order.id,
            status=change_order.status,
            docusign_envelope_id=change_order.docusign_envelope_id,
            box_file_id=change_order.box_file_id,
            box_file_url=change_order.box_file_url,
            box_unfiled=change_order.box_unfiled,
            message="Signed PDF is not ready yet or DocuSign could not return it.",
        )

    box_file_id, box_file_url, box_unfiled = file_change_order_pdf(
        address=change_order.address,
        pdf_bytes=signed_pdf,
        signed=True,
    )
    if box_file_id:
        change_order.box_file_id = box_file_id
        change_order.box_file_url = box_file_url
        change_order.box_unfiled = box_unfiled
        if box_unfiled:
            logger.warning("Signed change order %s filed to Unfiled Change Orders", change_order.id)
    change_order.status = "signed"
    await db.commit()
    try:
        await send_payment_email(db, change_order)
    except Exception:
        logger.exception("Signed change order %s payment email failed during manual sync", change_order.id)
    return ChangeOrderSignatureResponse(
        id=change_order.id,
        status=change_order.status,
        docusign_envelope_id=change_order.docusign_envelope_id,
        box_file_id=change_order.box_file_id,
        box_file_url=change_order.box_file_url,
        box_unfiled=change_order.box_unfiled,
        message="Signed change order synced from DocuSign and filed in Box.",
    )


async def _get_change_order_model(change_order_id: UUID, db: AsyncSession) -> ChangeOrderModel:
    result = await db.execute(
        select(ChangeOrderModel)
        .where(
            ChangeOrderModel.id == change_order_id,
            ChangeOrderModel.org_id == settings.default_org_id,
        )
        .options(selectinload(ChangeOrderModel.line_items))
    )
    change_order = result.scalar_one_or_none()
    if not change_order:
        raise HTTPException(status_code=404, detail="Change order not found")
    return change_order


def _request_change_order_extract(provider: ClaudeProvider, email_body: str) -> str:
    response = provider.client.messages.create(
        model=provider.model_version,
        max_tokens=2000,
        system=(
            "Return ONLY valid JSON. Extract a residential home-build change order draft "
            "from the email body. Use this exact schema: "
            '{"address": string, "client_name": string, "customer_email": string, '
            '"line_items": [{"description": string, "amount": number, "is_credit": boolean}], '
            '"payment_method": "add_to_mortgage" | "due_upon_receipt", "notes": string}. '
            "Use the Email line from the body as customer_email; this is the customer contact "
            "and default DocuSign signer email. "
            "Amounts are positive numbers. Mark is_credit true for credits, deductions, "
            "allowances, or amounts that reduce the contract price. Treat Due on Receipt, "
            "Due upon Receipt, and Due upon receipt as due_upon_receipt. If a field is unknown, "
            "use an empty string, empty array, or due_upon_receipt."
        ),
        messages=[
            {
                "role": "user",
                "content": f"Email body:\n\n{email_body}",
            }
        ],
    )
    return provider._extract_text_response(response)


def _normalize_change_order_draft(parsed: dict[str, Any]) -> ChangeOrderDraft:
    return ChangeOrderDraft(
        address=_as_text(parsed.get("address")),
        client_name=_as_text(parsed.get("client_name")),
        customer_email=_as_text(parsed.get("customer_email") or parsed.get("email")),
        co_number=_as_text(parsed.get("co_number")),
        date=_as_text(parsed.get("date")),
        line_items=_normalize_line_items(parsed.get("line_items")),
        payment_method=_normalize_payment_method(parsed.get("payment_method")),
        notes=_as_text(parsed.get("notes")),
    )


def _change_order_out(change_order: ChangeOrderModel) -> ChangeOrderOut:
    return ChangeOrderOut(
        id=change_order.id,
        lot_id=change_order.lot_id,
        address=change_order.address,
        client_name=change_order.client_name,
        customer_email=change_order.customer_email or "",
        co_number=change_order.co_number or "",
        date=change_order.date.isoformat() if change_order.date else "",
        line_items=[
            ChangeOrderLineItem(
                description=item.description,
                amount=item.amount,
                is_credit=item.is_credit,
            )
            for item in change_order.line_items
        ],
        payment_method=_normalize_payment_method(change_order.payment_method),
        notes=change_order.notes or "",
        status=change_order.status,
        subtotal=change_order.subtotal,
        gst=change_order.gst,
        total=change_order.total,
        docusign_envelope_id=change_order.docusign_envelope_id,
        plooto_payment_link=change_order.plooto_payment_link,
        plooto_status=change_order.plooto_status,
        qb_invoice_id=change_order.qb_invoice_id,
        qb_invoice_status=change_order.qb_invoice_status,
        qb_customer_id=change_order.qb_customer_id,
        qb_project_id=change_order.qb_project_id,
        qb_sync_error=change_order.qb_sync_error,
        payment_email_sent_at=change_order.payment_email_sent_at,
        box_file_id=change_order.box_file_id,
        box_file_url=change_order.box_file_url,
        box_unfiled=change_order.box_unfiled,
        archived_at=change_order.archived_at,
        created_at=change_order.created_at,
        updated_at=change_order.updated_at,
    )


def _valid_docusign_signature(raw_body: bytes, signature_header: str | None) -> bool:
    secret = settings.docusign_webhook_secret.strip()
    if not secret:
        return True
    if not signature_header:
        return False

    digest = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).digest()
    expected_base64 = base64.b64encode(digest).decode("ascii")
    expected_hex = digest.hex()
    return hmac.compare_digest(signature_header, expected_base64) or hmac.compare_digest(
        signature_header,
        expected_hex,
    )


def _parse_docusign_webhook(raw_body: bytes) -> tuple[str, str]:
    try:
        root = ElementTree.fromstring(raw_body)
    except ElementTree.ParseError as exc:
        logger.warning("Failed to parse DocuSign webhook XML: %s", exc)
        return "", ""

    envelope_id = ""
    status = ""
    for element in root.iter():
        tag_name = element.tag.rsplit("}", 1)[-1]
        text = (element.text or "").strip()
        if tag_name == "EnvelopeID" and text:
            envelope_id = text
        elif tag_name == "Status" and text:
            status = text
    return envelope_id, status


def _calculate_totals(line_items: list[ChangeOrderLineItem]) -> tuple[Decimal, Decimal, Decimal]:
    subtotal = sum(
        (
            -abs(item.amount) if item.is_credit else abs(item.amount)
            for item in line_items
        ),
        Decimal("0"),
    )
    subtotal = subtotal.quantize(Decimal("0.01"))
    gst = (subtotal * Decimal("0.05")).quantize(Decimal("0.01"))
    total = (subtotal + gst).quantize(Decimal("0.01"))
    return subtotal, gst, total


def _validate_email(value: str) -> None:
    try:
        TypeAdapter(EmailStr).validate_python(value)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail="Customer email must be a valid email address.") from exc


def _line_items_changed(existing: list[ChangeOrderLineItemModel], incoming: list[ChangeOrderLineItem]) -> bool:
    existing_values = [
        (item.description.strip(), Decimal(item.amount).quantize(Decimal("0.01")), bool(item.is_credit))
        for item in existing
    ]
    incoming_values = [
        (item.description.strip(), abs(item.amount).quantize(Decimal("0.01")), bool(item.is_credit))
        for item in incoming
    ]
    return existing_values != incoming_values


def _parse_date(value: str) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _normalize_line_items(value: object) -> list[ChangeOrderLineItem]:
    if not isinstance(value, list):
        return []

    line_items: list[ChangeOrderLineItem] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        line_items.append(
            ChangeOrderLineItem(
                description=_as_text(item.get("description")),
                amount=_as_decimal(item.get("amount")),
                is_credit=bool(item.get("is_credit")),
            )
        )
    return line_items


def _normalize_payment_method(value: object) -> Literal["add_to_mortgage", "due_upon_receipt"]:
    text = _as_text(value).lower().replace("-", " ").replace("_", " ")
    if "mortgage" in text:
        return "add_to_mortgage"
    return "due_upon_receipt"


def _as_decimal(value: object) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if value is None:
        return Decimal("0")
    try:
        return Decimal(str(value).replace("$", "").replace(",", "").strip())
    except Exception:
        return Decimal("0")


def _as_text(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _change_order_filename(change_order: ChangeOrderModel) -> str:
    label = change_order.co_number or str(change_order.id)
    address = "".join(
        character if character.isalnum() or character in (" ", "-", "_") else "-"
        for character in change_order.address
    ).strip()
    return f"{address or 'change-order'}-{label}.pdf"
