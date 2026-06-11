from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import BackgroundTasks
from fastapi import APIRouter
from fastapi import Depends
from fastapi import Header
from fastapi import HTTPException
from fastapi.responses import FileResponse
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from pydantic import Field

from app.core.config import settings
from app.services.appraisal_prep import AppraisalPrepBoxUnavailableError
from app.services.appraisal_prep import AppraisalPrepError
from app.services.appraisal_prep import create_appraisal_prep_package
from app.services.box import get_oauth_url
from app.services.box import handle_oauth_callback


router = APIRouter(tags=["box"])


def verify_api_key(x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None) -> None:
    if x_api_key != settings.office_hub_api_key:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


class AppraisalPrepRequest(BaseModel):
    box_file_ids: list[str] = Field(min_length=1, max_length=100)
    package_name: str = "appraisal-prep"


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


@router.post("/appraisal-prep", dependencies=[Depends(verify_api_key)])
async def create_appraisal_prep_download(
    request: AppraisalPrepRequest,
    background_tasks: BackgroundTasks,
) -> FileResponse:
    try:
        package = await asyncio.to_thread(
            create_appraisal_prep_package,
            box_file_ids=request.box_file_ids,
            package_name=request.package_name,
        )
    except AppraisalPrepBoxUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except AppraisalPrepError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    background_tasks.add_task(package.cleanup)
    return FileResponse(
        path=package.zip_path,
        media_type="application/zip",
        filename=package.filename,
        background=background_tasks,
    )
