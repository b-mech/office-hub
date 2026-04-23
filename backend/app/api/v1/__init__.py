from fastapi import APIRouter


router = APIRouter()


@router.get("/status")
async def status() -> dict[str, bool]:
    return {"ok": True}
