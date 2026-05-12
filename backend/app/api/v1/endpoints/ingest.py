from __future__ import annotations

from typing import Annotated
from typing import Any
from uuid import UUID

from fastapi import APIRouter
from fastapi import Depends
from fastapi import File
from fastapi import Form
from fastapi import HTTPException
from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.services.ingest import BudgetProjectMatchRequired
from app.services.ingest import IngestService


router = APIRouter(prefix="/ingest", tags=["ingest"])


@router.post("")
async def ingest_document(
    file: Annotated[UploadFile, File()],
    doc_type: Annotated[str, Form()],
    matched_lot_id: Annotated[UUID | None, Form()] = None,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    if doc_type == "budget":
        allowed_content_types = {
            "application/octet-stream",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "text/csv",
            "application/csv",
            "text/plain",
            None,
        }
    else:
        allowed_content_types = {"application/pdf", "application/octet-stream", None}

    if file.content_type not in allowed_content_types:
        raise HTTPException(status_code=400, detail="Unsupported file type for this import")

    try:
        if doc_type == "budget":
            result = await IngestService(db).ingest_budget_file(file=file, matched_lot_id=matched_lot_id)
        else:
            result = await IngestService(db).ingest_pdf(file=file, doc_type=doc_type)
    except BudgetProjectMatchRequired as exc:
        raise HTTPException(status_code=409, detail=exc.detail) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    response: dict[str, Any] = {
        "document_id": result.document_id,
        "status": result.status.value,
        "extraction_summary": result.extraction_summary,
        "resource_type": result.resource_type,
    }
    if result.resource_id is not None:
        response["resource_id"] = result.resource_id
        if result.resource_type == "budget":
            response["budget_id"] = result.resource_id
    return response
