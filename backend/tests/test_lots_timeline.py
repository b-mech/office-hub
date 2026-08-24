from __future__ import annotations

import os
from typing import Any


os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/test")
os.environ.setdefault("MINIO_URL", "http://localhost:9000")
os.environ.setdefault("MINIO_ROOT_USER", "test")
os.environ.setdefault("MINIO_ROOT_PASSWORD", "test")
os.environ.setdefault("IMAP_HOST", "localhost")
os.environ.setdefault("IMAP_USER", "test")
os.environ.setdefault("IMAP_PASSWORD", "test")
os.environ.setdefault("IMAP_FOLDER", "INBOX")
os.environ.setdefault("ANTHROPIC_API_KEY", "test")
os.environ.setdefault("OPENAI_API_KEY", "test")
os.environ.setdefault("ACTIVE_MODEL_PROVIDER", "anthropic")
os.environ.setdefault("SECRET_KEY", "test")
os.environ.setdefault("OFFICE_HUB_API_KEY", "test")
os.environ.setdefault("DEFAULT_ORG_ID", "00000000-0000-0000-0000-000000000001")
os.environ.setdefault("ENVIRONMENT", "test")

from app.modules.lots.router import list_otp_timeline
from app.modules.lots.router import router


class _EmptyMappings:
    def all(self) -> list[dict[str, Any]]:
        return []


class _EmptyResult:
    def mappings(self) -> _EmptyMappings:
        return _EmptyMappings()


class _RecordingSession:
    statement: str = ""

    async def execute(self, statement: object, _: dict[str, str]) -> _EmptyResult:
        self.statement = str(statement)
        return _EmptyResult()


async def test_timeline_excludes_paid_land_and_sale_deposits() -> None:
    session = _RecordingSession()

    result = await list_otp_timeline(session)  # type: ignore[arg-type]

    assert result == []
    assert "sds.paid_at IS NULL" in session.statement
    assert "lds.paid_at IS NULL" in session.statement


def test_timeline_has_no_legacy_api_key_dependency() -> None:
    route = next(route for route in router.routes if route.path == "/api/v1/lots/timeline")

    dependency_names = {
        dependency.call.__name__
        for dependency in route.dependant.dependencies
        if dependency.call is not None
    }
    assert "verify_api_key" not in dependency_names
