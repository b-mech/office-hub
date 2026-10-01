from __future__ import annotations

import io
import json
from typing import Annotated, Any, Callable
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Header, HTTPException, Request, Response, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authorization import current_user
from app.core.config import settings
from app.core.database import get_db
from app.models.core import User, UserRole
from app.models.presales import PresaleApprovalLetter
from app.schemas.presales import (
    ApprovalLetterIntake,
    ApprovalLetterUpdate,
    ContactLenderRequest,
    FundingPartnerRulePatch,
    FundingPartnerRuleWrite,
    MarkPackageSentRequest,
    MarkPresaleRequest,
    MarkRequestedRequest,
    PackageItemAction,
    RejectApprovalLetterRequest,
    TaskCompleteRequest,
)
from app.services import presales
from app.services.minio_financing import get_financing_document
from app.workers.presales import _extract


router = APIRouter(prefix="/api/presales", tags=["presales"])


def verify_extension_api_key(
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
) -> None:
    if x_api_key != settings.office_hub_api_key:
        raise HTTPException(status_code=401, detail="Invalid Office Hub extension API key")


def require_presale_permission(permission: str, *, write: bool = True) -> Callable[[Request], User | None]:
    def dependency(request: Request) -> User | None:
        if not settings.auth_enforced:
            return None
        user = current_user(request)
        if user.role == UserRole.ADMIN:
            return user
        level = (user.permissions or {}).get(permission) or (user.permissions or {}).get("presales", "none")
        allowed = level in ({"editor"} if write else {"viewer", "editor"})
        if not allowed:
            raise HTTPException(status_code=403, detail=f"Permission required: {permission}")
        return user
    return dependency


@router.get("/extension/lots", dependencies=[Depends(verify_extension_api_key)])
async def extension_lot_options(
    search: str = "",
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    return await presales.list_extension_lots(db, search)


@router.get("/lot-options", dependencies=[Depends(require_presale_permission("presales.approval_letters.review", write=False))])
async def lot_options(search: str = "", db: AsyncSession = Depends(get_db)) -> list[dict[str, Any]]:
    return await presales.list_extension_lots(db, search)


@router.post("/approval-letters/intake", status_code=202, dependencies=[Depends(verify_extension_api_key)])
async def intake_approval_letter(
    data: ApprovalLetterIntake,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        records = await presales.create_intake_records(
            db,
            lot_id=data.lot_id,
            mark_as_presale=data.mark_as_presale,
            email=data.email,
            attachments=data.attachments,
        )
    except presales.DuplicateApprovalLetterError as exc:
        raise HTTPException(
            status_code=409,
            detail={"message": "Approval letter already captured for this lot", "approval_letter_id": str(exc.existing_id)},
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Extraction runs as an application background task in the current deployment.
    # A Redis broker can accept Celery messages even when no worker is running, which
    # would leave captured letters indefinitely stuck in pending_extraction.
    for record in records:
        background_tasks.add_task(_extract, record.id)
    return {
        "approval_letter_id": str(records[0].id),
        "approval_letter_ids": [str(record.id) for record in records],
    }


@router.get("/board", dependencies=[Depends(require_presale_permission("presales.approval_letters.review", write=False))])
async def presales_board(db: AsyncSession = Depends(get_db)) -> list[dict[str, Any]]:
    return await presales.list_presales_board(db)


@router.get("/queue", dependencies=[Depends(require_presale_permission("presales.approval_letters.review", write=False))])
async def funding_queue(db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    return await presales.list_review_queue(db)


@router.get("/unmatched", dependencies=[Depends(require_presale_permission("presales.approval_letters.review", write=False))])
async def unmatched_letters(db: AsyncSession = Depends(get_db)) -> list[dict[str, Any]]:
    return await presales.list_unmatched(db)


@router.get("/lots/{lot_id}", dependencies=[Depends(require_presale_permission("presales.approval_letters.review", write=False))])
async def lot_detail(lot_id: UUID, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    try:
        return await presales.get_lot_detail(db, lot_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/lots/{lot_id}", dependencies=[Depends(require_presale_permission("presales.approval_letters.review"))])
async def update_lot(
    lot_id: UUID,
    data: MarkPresaleRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        return await presales.set_lot_presale(
            db,
            lot_id,
            sale_type=data.sale_type,
            building_type=data.building_type,
            realtor_name=data.realtor_name,
            realtor_email=str(data.realtor_email) if data.realtor_email else None,
            realtor_brokerage=data.realtor_brokerage,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/lots/{lot_id}/approval-letter/requested", dependencies=[Depends(require_presale_permission("presales.approval_letters.review"))])
async def mark_approval_letter_requested(
    lot_id: UUID,
    data: MarkRequestedRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        letter = await presales.mark_letter_requested(db, lot_id, requested_from=data.requested_from)
        return presales._letter_payload(letter) or {}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/approval-letters/{letter_id}", dependencies=[Depends(require_presale_permission("presales.approval_letters.review", write=False))])
async def approval_letter(letter_id: UUID, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    letter = await db.get(PresaleApprovalLetter, letter_id)
    if letter is None:
        raise HTTPException(status_code=404, detail="Approval letter not found")
    return presales._letter_payload(letter) or {}


@router.patch("/approval-letters/{letter_id}", dependencies=[Depends(require_presale_permission("presales.approval_letters.review"))])
async def update_approval_letter(
    letter_id: UUID,
    data: ApprovalLetterUpdate,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    fields = data.model_fields_set
    try:
        letter = await presales.update_letter(
            db,
            letter_id,
            lot_id=data.lot_id if "lot_id" in fields else ...,
            mark_as_presale=data.mark_as_presale,
            extracted=data.extracted,
            quality_score=data.quality_score if "quality_score" in fields else ...,
        )
        return presales._letter_payload(letter) or {}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/approval-letters/{letter_id}/contacted", dependencies=[Depends(require_presale_permission("presales.approval_letters.review"))])
async def contacted_lender(
    letter_id: UUID,
    data: ContactLenderRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        letter = await presales.contact_lender(db, letter_id, data.notes)
        return presales._letter_payload(letter) or {}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/approval-letters/{letter_id}/approve", dependencies=[Depends(require_presale_permission("presales.approval_letters.review"))])
async def approve_approval_letter(
    letter_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    user = getattr(request.state, "user", None)
    try:
        return await presales.approve_letter(db, letter_id, user.id if user else None)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/approval-letters/{letter_id}/reject", dependencies=[Depends(require_presale_permission("presales.approval_letters.review"))])
async def reject_approval_letter(
    letter_id: UUID,
    data: RejectApprovalLetterRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    user = getattr(request.state, "user", None)
    try:
        letter = await presales.reject_letter(db, letter_id, reason=data.reason, reviewer_id=user.id if user else None)
        return presales._letter_payload(letter) or {}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/approval-letters/{letter_id}/file", dependencies=[Depends(require_presale_permission("presales.approval_letters.review", write=False))])
async def approval_letter_file(letter_id: UUID, db: AsyncSession = Depends(get_db)) -> StreamingResponse:
    letter = await db.get(PresaleApprovalLetter, letter_id)
    if letter is None or not letter.file_key:
        raise HTTPException(status_code=404, detail="Approval letter file not found")
    content = get_financing_document(key=letter.file_key)
    return StreamingResponse(
        io.BytesIO(content),
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{letter.original_filename or "approval-letter.pdf"}"'},
    )


@router.post("/lots/{lot_id}/package-items/{item_type}/action", dependencies=[Depends(require_presale_permission("presales.approval_letters.review"))])
async def package_item_action(
    lot_id: UUID,
    item_type: str,
    data: PackageItemAction,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        return await presales.mark_package_item_action(db, lot_id, item_type, data.action)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/lots/{lot_id}/package-items/{item_type}/upload", dependencies=[Depends(require_presale_permission("presales.approval_letters.review"))])
async def upload_package_item(
    lot_id: UUID,
    item_type: str,
    file: Annotated[UploadFile, File()],
    metadata_json: Annotated[str, Form()] = "{}",
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        metadata = json.loads(metadata_json or "{}")
        if not isinstance(metadata, dict):
            raise ValueError("metadata_json must be an object")
        content = await file.read()
        return await presales.store_package_document(
            db,
            lot_id=lot_id,
            item_type=item_type,
            filename=file.filename or f"{item_type}.pdf",
            content=content,
            content_type=file.content_type or "application/pdf",
            metadata=metadata,
        )
    except (ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/tasks/{task_id}/complete", dependencies=[Depends(require_presale_permission("presales.approval_letters.review"))])
async def complete_presale_task(
    task_id: UUID,
    data: TaskCompleteRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        task = await presales.complete_task(db, task_id, data.notes)
        return presales._task_payload(task)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/lots/{lot_id}/packages/{partner_code}/draft", dependencies=[Depends(require_presale_permission("presales.package.draft"))])
async def draft_package(lot_id: UUID, partner_code: str, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    try:
        return await presales.create_package_draft(db, lot_id, partner_code.upper())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/lots/{lot_id}/packages/{partner_code}/fallback.zip", dependencies=[Depends(require_presale_permission("presales.package.draft", write=False))])
async def download_package(lot_id: UUID, partner_code: str, db: AsyncSession = Depends(get_db)) -> StreamingResponse:
    try:
        content, filename = await presales.package_fallback_zip(db, lot_id, partner_code.upper())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return StreamingResponse(io.BytesIO(content), media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.post("/lots/{lot_id}/packages/sent", dependencies=[Depends(require_presale_permission("presales.package.draft"))])
async def package_sent(lot_id: UUID, data: MarkPackageSentRequest, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    try:
        return await presales.mark_package_sent(db, lot_id, data.partner_code.upper())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/partner-rules", dependencies=[Depends(require_presale_permission("presales.partner_rules.manage", write=False))])
async def partner_rules(db: AsyncSession = Depends(get_db)) -> list[dict[str, Any]]:
    return await presales.list_partner_rules(db)


@router.post("/partner-rules", status_code=201, dependencies=[Depends(require_presale_permission("presales.partner_rules.manage"))])
async def create_partner_rule(data: FundingPartnerRuleWrite, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    try:
        return await presales.create_partner_rule(db, data.model_dump(mode="json"))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.patch("/partner-rules/{partner_code}", dependencies=[Depends(require_presale_permission("presales.partner_rules.manage"))])
async def update_partner_rule(partner_code: str, data: FundingPartnerRulePatch, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    try:
        return await presales.update_partner_rule(db, partner_code, data.model_dump(exclude_unset=True, mode="json"))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/partner-rules/{partner_code}", status_code=204, response_class=Response, response_model=None, dependencies=[Depends(require_presale_permission("presales.partner_rules.manage"))])
async def delete_partner_rule(partner_code: str, db: AsyncSession = Depends(get_db)) -> Response:
    try:
        await presales.delete_partner_rule(db, partner_code)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Response(status_code=204)


@router.get("/notifications", dependencies=[Depends(require_presale_permission("presales.approval_letters.review", write=False))])
async def notifications(unread_only: bool = False, db: AsyncSession = Depends(get_db)) -> list[dict[str, Any]]:
    return await presales.list_notifications(db, unread_only=unread_only)


@router.post("/notifications/{notification_id}/read", status_code=204, response_class=Response, response_model=None, dependencies=[Depends(require_presale_permission("presales.approval_letters.review"))])
async def notification_read(notification_id: UUID, db: AsyncSession = Depends(get_db)) -> Response:
    try:
        await presales.mark_notification_read(db, notification_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Response(status_code=204)
