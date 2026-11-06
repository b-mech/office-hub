"""Every route under a tenant-aware prefix must resolve the tenant itself.

The auth middleware exempts these prefixes from the legacy "default org
members only" guard, so a route here without ``get_tenant`` would be open to
any signed-in user of any org.
"""
from __future__ import annotations

import os

for key, value in {
    "DATABASE_URL": "postgresql+asyncpg://user:pass@localhost/test",
    "MINIO_URL": "http://localhost:9000",
    "MINIO_ROOT_USER": "test",
    "MINIO_ROOT_PASSWORD": "test",
    "IMAP_HOST": "localhost",
    "IMAP_USER": "test",
    "IMAP_PASSWORD": "test",
    "IMAP_FOLDER": "INBOX",
    "ANTHROPIC_API_KEY": "test",
    "OPENAI_API_KEY": "test",
    "ACTIVE_MODEL_PROVIDER": "test",
    "SECRET_KEY": "test",
    "OFFICE_HUB_API_KEY": "test",
    "DEFAULT_ORG_ID": "00000000-0000-0000-0000-000000000001",
    "ENVIRONMENT": "test",
}.items():
    os.environ.setdefault(key, value)

from fastapi.routing import APIRoute

from app.main import app
from app.middleware.auth import is_tenant_aware_path


def _dependency_names(route: APIRoute) -> set[str]:
    names: set[str] = set()
    stack = list(route.dependant.dependencies)
    while stack:
        dependency = stack.pop()
        if dependency.call is not None:
            names.add(dependency.call.__name__)
        stack.extend(dependency.dependencies)
    return names


def test_tenant_aware_routes_resolve_tenant() -> None:
    missing = [
        f"{sorted(route.methods)} {route.path}"
        for route in app.routes
        if isinstance(route, APIRoute)
        and is_tenant_aware_path(route.path)
        and not route.path.startswith("/api/auth/")
        and "get_tenant" not in _dependency_names(route)
    ]
    assert missing == []


def test_tender_and_project_routes_are_tenant_aware() -> None:
    paths = {route.path for route in app.routes if isinstance(route, APIRoute)}
    tender = {path for path in paths if "tender" in path}
    assert tender and all(is_tenant_aware_path(path) for path in tender)
    for path in ("/api/v1/projects", "/api/v1/lots/{lot_id}", "/api/v1/clients", "/api/v1/workspace/dashboard"):
        assert path in paths and is_tenant_aware_path(path)
