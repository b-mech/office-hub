import logging
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import router as api_v1_router
from app.modules.costbook.router import router as costbook_router
from app.modules.lots.router import projects_router
from app.modules.lots.router import router as lots_router
from app.routers.box import router as box_router
from app.routers.change_orders import router as change_orders_router
from app.routers.financing import router as financing_router
from app.routers.facility_assignments import router as facility_assignments_router
from app.routers.lenders import router as lenders_router
from app.routers.users import router as users_router
from app.core.config import settings


logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    logger.info("Office Hub API starting")
    yield


app = FastAPI(
    title="Office Hub API",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_origin_regex=settings.cors_origin_regex,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health_check() -> dict[str, str]:
    return {
        "status": "ok",
        "environment": settings.environment,
        "version": app.version,
    }


app.include_router(api_v1_router, prefix="/api/v1")
app.include_router(box_router, prefix="/api/v1/box")
app.include_router(change_orders_router, prefix="/api/v1")
app.include_router(users_router, prefix="/api/v1")
app.include_router(financing_router)
app.include_router(facility_assignments_router)
app.include_router(lenders_router)
app.include_router(costbook_router)
app.include_router(lots_router)
app.include_router(projects_router)
