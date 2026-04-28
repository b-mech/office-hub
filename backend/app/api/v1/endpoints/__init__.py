from fastapi import APIRouter

from app.api.v1.endpoints.documents import router as documents_router
from app.api.v1.endpoints.ingest import router as ingest_router


router = APIRouter()
router.include_router(documents_router)
router.include_router(ingest_router)


__all__ = ["router"]
