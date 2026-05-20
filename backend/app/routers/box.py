from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter
from fastapi import Depends
from fastapi import Header
from fastapi import HTTPException
from fastapi.responses import RedirectResponse

from app.core.config import settings
from app.services.box import get_oauth_url
from app.services.box import handle_oauth_callback


router = APIRouter(tags=["box"])


def verify_api_key(x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None) -> None:
    if x_api_key != settings.office_hub_api_key:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


@router.get("/connect")
async def connect_box() -> dict[str, str]:
    return {"auth_url": get_oauth_url()}


@router.get("/oauth/callback")
async def box_oauth_callback(code: str, state: str) -> RedirectResponse:
    success = handle_oauth_callback(code=code, state=state)
    suffix = "box_connected=true" if success else "box_error=true"
    return RedirectResponse(url=f"/settings/imports?{suffix}")


@router.get("/status", dependencies=[Depends(verify_api_key)])
async def box_status() -> dict[str, bool]:
    return {
        "configured": settings.box_configured,
        "authenticated": settings.box_authenticated,
    }
