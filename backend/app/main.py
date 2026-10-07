import asyncio
import logging
from contextlib import asynccontextmanager
from contextlib import suppress
from collections.abc import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1 import router as api_v1_router
from app.modules.costbook.router import router as costbook_router
from app.modules.developments.router import router as developments_router
from app.modules.lots.router import projects_router
from app.modules.lots.router import router as lots_router
from app.routers.box import router as box_router
from app.routers.change_orders import router as change_orders_router
from app.routers.construction_stage_history import router as construction_stage_history_router
from app.routers.financing import router as financing_router
from app.routers.facility_assignments import router as facility_assignments_router
from app.routers.financial_summaries import router as financial_summaries_router
from app.routers.lenders import router as lenders_router
from app.routers.maintenance import router as maintenance_router
from app.routers.program_allocations import router as program_allocations_router
from app.routers.presales import router as presales_router
from app.routers.rentals import inspections_router, router as rentals_router
from app.routers.tendering import router as tendering_router
from app.routers.users import router as users_router
from app.core.config import settings
from app.middleware.auth import AuthenticationMiddleware
from app.routers.auth import router as auth_router
from app.services.maintenance.scheduler_health import (
    alert_if_scheduler_stale,
    alert_if_subscription_scheduler_stale,
    scheduler_health,
    subscription_scheduler_health,
)


logger = logging.getLogger("uvicorn.error")


def _scheduler_health_required() -> bool:
    return settings.environment.casefold() not in {"development", "test", "testing"}


async def _scheduler_monitor() -> None:
    while True:
        try:
            await alert_if_scheduler_stale()
            await alert_if_subscription_scheduler_stale()
        except Exception:
            logger.exception("Maintenance escalation scheduler monitor failed")
        await asyncio.sleep(60)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    logger.info("Office Hub API starting")
    if settings.maintenance_enabled:
        logger.info("PRIVI maintenance enabled")
    else:
        logger.info("PRIVI maintenance disabled: %s", "; ".join(settings.maintenance_config_issues))
    monitor = asyncio.create_task(_scheduler_monitor()) if _scheduler_health_required() else None
    try:
        yield
    finally:
        if monitor is not None:
            monitor.cancel()
            with suppress(asyncio.CancelledError):
                await monitor


app = FastAPI(
    title="Office Hub API",
    version="0.1.0",
    lifespan=lifespan,
)

if settings.auth_enforced:
    app.add_middleware(AuthenticationMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_origin_regex=settings.cors_origin_regex,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", response_model=None)
async def health_check() -> dict[str, str | None] | JSONResponse:
    payload: dict[str, str | None] = {
        "status": "ok",
        "environment": settings.environment,
        "version": app.version,
    }
    if not _scheduler_health_required():
        return payload
    scheduler = await scheduler_health()
    subscription_scheduler = await subscription_scheduler_health()
    payload["maintenance_escalation_last_run"] = (
        scheduler.last_run.isoformat() if scheduler.last_run else None
    )
    payload["ringcentral_renewal_last_run"] = (
        subscription_scheduler.last_run.isoformat() if subscription_scheduler.last_run else None
    )
    payload["ringcentral_subscription_expires_at"] = (
        subscription_scheduler.expires_at.isoformat()
        if subscription_scheduler.expires_at
        else None
    )
    if not scheduler.healthy or not subscription_scheduler.healthy:
        payload["status"] = "unhealthy"
        details = [
            detail
            for healthy, detail in (
                (scheduler.healthy, scheduler.detail),
                (subscription_scheduler.healthy, subscription_scheduler.detail),
            )
            if not healthy
        ]
        payload["detail"] = "; ".join(details)
        return JSONResponse(status_code=503, content=payload)
    return payload


app.include_router(api_v1_router, prefix="/api/v1")
app.include_router(auth_router)
app.include_router(box_router, prefix="/api/v1/box")
app.include_router(change_orders_router, prefix="/api/v1")
app.include_router(construction_stage_history_router)
app.include_router(users_router, prefix="/api/v1")
app.include_router(financing_router)
app.include_router(facility_assignments_router)
app.include_router(financial_summaries_router)
app.include_router(lenders_router)
app.include_router(maintenance_router)
app.include_router(program_allocations_router)
app.include_router(presales_router)
app.include_router(rentals_router)
app.include_router(inspections_router)
app.include_router(tendering_router)
app.include_router(costbook_router)
app.include_router(developments_router)
app.include_router(lots_router)
app.include_router(projects_router)
