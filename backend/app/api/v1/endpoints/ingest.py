from __future__ import annotations

from typing import Annotated
from typing import Any

from fastapi import APIRouter
from fastapi import Depends
from fastapi import File
from fastapi import Form
from fastapi import HTTPException
from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.services.ingest import IngestService


router = APIRouter(prefix="/ingest", tags=["ingest"])


@router.post("")
async def ingest_document(
    file: Annotated[UploadFile, File()],
    doc_type: Annotated[str, Form()],
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    if file.content_type not in {"application/pdf", "application/octet-stream", None}:
        raise HTTPException(status_code=400, detail="Only PDF uploads are supported")

    try:
        result = await IngestService(db).ingest_pdf(file=file, doc_type=doc_type)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return {
        "document_id": result.document_id,
        "status": result.status.value,
        "extraction_summary": result.extraction_summary,
    }
