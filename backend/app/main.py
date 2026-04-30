import logging
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import router as api_v1_router
from app.modules.costbook.router import router as costbook_router
from app.modules.lots.router import router as lots_router
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
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "https://mail.google.com",
    ],
    allow_origin_regex=r"(chrome-extension://.*|http://192\.168\.\d+\.\d+:3000)",
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
app.include_router(costbook_router)
app.include_router(lots_router)
