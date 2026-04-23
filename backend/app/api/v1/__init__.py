from fastapi import APIRouter

from app.api.v1.endpoints import router as endpoints_router


router = APIRouter()


@router.get("/status")
async def status() -> dict[str, bool]:
    return {"ok": True}


router.include_router(endpoints_router)
