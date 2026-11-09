"""API security tests for tenant isolation against a dedicated, migrated test database.

Runs only when OFFICEHUB_INTEGRATION_DB names the database in DATABASE_URL and
that name contains "test" (never the production ``officehub`` database), e.g.::

    OFFICEHUB_INTEGRATION_DB=officehub_workspace_test \
    DATABASE_URL=postgresql+asyncpg://.../officehub_workspace_test pytest

Fixtures are committed with a unique suffix so the middleware's own session can
see them. MinIO, mail, DocuSign, and Slack are never contacted: file content
and upload helpers are monkeypatched.
"""
from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from types import SimpleNamespace
from uuid import UUID
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool


DB_NAME = os.environ.get("OFFICEHUB_INTEGRATION_DB", "")
DATABASE_URL = os.environ.get("DATABASE_URL", "")
ENABLED = bool(DB_NAME) and "test" in DB_NAME and DB_NAME != "officehub" and DATABASE_URL.rsplit("/", 1)[-1] == DB_NAME
pytestmark = pytest.mark.skipif(not ENABLED, reason="set OFFICEHUB_INTEGRATION_DB to a dedicated *test* database")

if ENABLED:
    from app.core.auth import create_access_token
    from app.core.config import settings
    from app.core.database import get_db
    from app.main import app
    from app.middleware import auth as auth_middleware
    from app.services import tender_markups
    from app.services import tendering
    from app.routers import users as users_router


@dataclass
class World:
    sfx: str
    ch: UUID
    ps: UUID
    ch_slug: str
    ps_slug: str
    users: dict[str, UUID]
    lots: dict[str, UUID]
    props: dict[str, UUID]
    packages: dict[str, UUID]
    documents: dict[str, UUID]
    markups: dict[str, UUID]
    bids: dict[str, UUID]
    bid_documents: dict[str, UUID]
    contacts: dict[str, UUID]
    category: UUID
    contractor: UUID


def _engine():
    return create_async_engine(DATABASE_URL, poolclass=NullPool)


async def _build_world() -> World:
    sfx = uuid4().hex[:8]
    engine = _engine()
    async with engine.begin() as conn:
        async def one(sql: str, **params: object) -> UUID:
            return (await conn.execute(text(sql + " RETURNING id"), params)).scalar_one()

        ch_slug, ps_slug = f"ch-test-{sfx}", f"ps-test-{sfx}"
        ch = await one("INSERT INTO core.orgs (name, slug, member_project_scope, land_enabled) VALUES (:n, :s, 'org', true)",
                       n=f"CH Test {sfx}", s=ch_slug)
        ps = await one("INSERT INTO core.orgs (name, slug) VALUES (:n, :s)", n=f"PS Test {sfx}", s=ps_slug)
        users: dict[str, UUID] = {}
        specs = [
            ("ch_admin", ch, "admin", False, [(ch, "tenant_admin")], {}),
            ("ch_staff", ch, "staff", False, [(ch, "member")], {}),
            ("ch_readonly", ch, "readonly", False, [(ch, "member")], {}),
            ("superadmin", ch, "admin", True, [(ch, "tenant_admin")], {}),
            ("ps_admin", ps, "staff", False, [(ps, "tenant_admin")], {}),
            ("ps_member", ps, "staff", False, [(ps, "member")], {}),
            ("ps_viewer", ps, "staff", False, [(ps, "member")], {}),
            ("ps_unassigned", ps, "staff", False, [(ps, "member")], {}),
            ("ps_rentals_perm", ps, "staff", False, [(ps, "member")], {"rentals": "editor"}),
        ]
        for index, (key, home, role, superadmin, memberships, perms) in enumerate(specs):
            users[key] = await one(
                "INSERT INTO core.users (org_id, email, full_name, role, is_active, is_superadmin, permissions, created_at)"
                " VALUES (:o, :e, :f, :r, true, :sa, CAST(:p AS jsonb), now() + make_interval(secs => :i))",
                o=home, e=f"{key}-{sfx}@example.test", f=f"{key} {sfx}", r=role, sa=superadmin,
                p=__import__("json").dumps(perms), i=index,
            )
            for org_id, org_role in memberships:
                await conn.execute(text("INSERT INTO core.user_org_memberships (user_id, org_id, role) VALUES (:u, :o, :r)"),
                                   {"u": users[key], "o": org_id, "r": org_role})
        dev_ch = await one("INSERT INTO core.developments (org_id, name, name_normalized, development_type) VALUES (:o, :n, :n, 'community')",
                           o=ch, n=f"ch community {sfx}")
        dev_ps = await one("INSERT INTO core.developments (org_id, name, name_normalized, development_type) VALUES (:o, :n, :n, 'community')",
                           o=ps, n=f"ps community {sfx}")
        props: dict[str, UUID] = {}
        lots: dict[str, UUID] = {}
        for key, dev, trigger in [("ch_project", dev_ch, "spec"), ("ch_land", dev_ch, None),
                                  ("ps_a", dev_ps, "otp"), ("ps_b", dev_ps, "spec")]:
            props[key] = await one("INSERT INTO core.properties (address, address_normalized) VALUES (:a, :a)",
                                   a=f"{key} {sfx} street")
            lots[key] = await one(
                "INSERT INTO core.lots (development_id, legal_description_normalized, trigger_type, property_id, civic_address)"
                " VALUES (:d, :l, :t, :p, :c)",
                d=dev, l=f"TEST {sfx} {key}", t=trigger, p=props[key], c=f"{key} {sfx} street",
            )
        props["orphan"] = await one("INSERT INTO core.properties (address, address_normalized) VALUES (:a, :a)",
                                    a=f"orphan {sfx} street")
        await conn.execute(text("INSERT INTO core.project_members (lot_id, user_id, role) VALUES (:l, :u, 'editor'), (:l, :v, 'viewer')"),
                           {"l": lots["ps_a"], "u": users["ps_member"], "v": users["ps_viewer"]})
        category = await one("INSERT INTO core.contractor_categories (name, slug) VALUES (:n, :n)", n=f"cat-{sfx}")
        contractor = await one("INSERT INTO core.contractors (name) VALUES (:n)", n=f"contractor {sfx}")
        packages: dict[str, UUID] = {}
        documents: dict[str, UUID] = {}
        markups: dict[str, UUID] = {}
        bids: dict[str, UUID] = {}
        bid_documents: dict[str, UUID] = {}
        for key in ("ch_project", "ps_a", "ps_b", "orphan"):
            packages[key] = await one(
                "INSERT INTO core.tender_packages (id, property_id, category_id, scope_description, status, due_date)"
                " VALUES (gen_random_uuid(), :p, :c, :s, 'sent', CURRENT_DATE + 7)",
                p=props[key], c=category, s=f"scope {key}",
            )
            documents[key] = await one(
                "INSERT INTO documents.tender_documents (id, tender_package_id, document_type, file_path, original_filename)"
                " VALUES (gen_random_uuid(), :p, 'plan', :f, 'plan.pdf')", p=packages[key], f=f"tender/{sfx}/{key}.pdf")
            markups[key] = await one(
                "INSERT INTO documents.tender_document_markups (id, tender_document_id, version_number, annotation_data, flattened_pdf_path)"
                " VALUES (gen_random_uuid(), :d, 1, '{}'::jsonb, :f)", d=documents[key], f=f"tender/{sfx}/{key}-m.pdf")
            bids[key] = await one(
                "INSERT INTO core.tender_bids (id, tender_package_id, contractor_id) VALUES (gen_random_uuid(), :p, :c)",
                p=packages[key], c=contractor)
            bid_documents[key] = await one(
                "INSERT INTO documents.tender_bid_documents (id, tender_bid_id, file_path, original_filename)"
                " VALUES (gen_random_uuid(), :b, :f, 'quote.pdf')", b=bids[key], f=f"bids/{sfx}/{key}.pdf")
        contacts = {
            "ch": await one("INSERT INTO core.contacts (org_id, contact_type, full_name) VALUES (:o, 'buyer', :n)", o=ch, n=f"CH Buyer {sfx}"),
            "ps": await one("INSERT INTO core.contacts (org_id, contact_type, full_name) VALUES (:o, 'buyer', :n)", o=ps, n=f"PS Buyer {sfx}"),
        }
    await engine.dispose()
    return World(sfx, ch, ps, ch_slug, ps_slug, users, lots, props, packages, documents, markups, bids,
                 bid_documents, contacts, category, contractor)


@pytest.fixture(scope="module")
def world() -> World:
    return asyncio.run(_build_world())


@pytest.fixture(autouse=True)
def wired(world: World, monkeypatch: pytest.MonkeyPatch):
    factory = async_sessionmaker(_engine(), expire_on_commit=False)

    async def test_db():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_db] = test_db
    monkeypatch.setattr(auth_middleware, "AsyncSessionLocal", factory)
    monkeypatch.setattr(settings, "default_org_id", world.ch)
    monkeypatch.setattr(settings, "auth_enforced", True)

    async def fake_content(document: object) -> bytes:
        return b"%PDF-1.4 test"

    monkeypatch.setattr(tendering, "get_tender_document_content", fake_content)
    monkeypatch.setattr(tendering, "get_tender_bid_document_content", fake_content)
    monkeypatch.setattr(tender_markups, "get_flattened_pdf", fake_content)
    yield factory
    app.dependency_overrides.clear()


async def call(method: str, path: str, user: UUID | None = None, org: str | None = None, **kwargs: object) -> httpx.Response:
    headers = dict(kwargs.pop("headers", {}) or {})  # type: ignore[arg-type]
    if user is not None:
        headers["Authorization"] = f"Bearer {create_access_token(user)}"
    if org is not None:
        headers["X-OfficeHub-Org"] = org
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        return await client.request(method, path, headers=headers, **kwargs)


def ids(response: httpx.Response) -> set[str]:
    assert response.status_code == 200, response.text
    return {item["id"] for item in response.json()}


async def sql(factory, statement: str, **params: object) -> object:
    async with factory() as session:
        result = await session.execute(text(statement), params)
        await session.commit()
        return result


def tender_reads(world: World, key: str) -> list[str]:
    return [
        f"/api/properties/{world.props[key]}/tender-packages",
        f"/api/tender-packages/{world.packages[key]}",
        f"/api/tender-packages/{world.packages[key]}/documents",
        f"/api/tender-packages/{world.packages[key]}/bids",
        f"/api/tender-packages/{world.packages[key]}/comparison",
        f"/api/tender-documents/{world.documents[key]}/content",
        f"/api/tender-documents/{world.documents[key]}/markups",
        f"/api/tender-document-markups/{world.markups[key]}",
        f"/api/tender-document-markups/{world.markups[key]}/flattened",
        f"/api/tender-bid-documents/{world.bid_documents[key]}/content",
    ]


def tender_writes(world: World, key: str) -> list[tuple[str, str, dict[str, object]]]:
    pdf = {"files": {"file": ("x.pdf", b"%PDF-1.4", "application/pdf")}}
    return [
        ("POST", f"/api/properties/{world.props[key]}/tender-packages",
         {"json": {"category_id": str(world.category), "scope_description": "x"}}),
        ("PATCH", f"/api/tender-packages/{world.packages[key]}", {"json": {"status": "bids_in"}}),
        ("POST", f"/api/tender-packages/{world.packages[key]}/documents",
         {**pdf, "data": {"document_type": "plan"}}),
        ("DELETE", f"/api/tender-documents/{world.documents[key]}", {}),
        ("POST", f"/api/tender-documents/{world.documents[key]}/markups", {"json": {"annotation_data": {}}}),
        ("POST", f"/api/tender-packages/{world.packages[key]}/bids", {"json": {"contractor_id": str(world.contractor)}}),
        ("PATCH", f"/api/tender-bids/{world.bids[key]}", {"json": {"reviewer_notes": "x"}}),
        ("POST", f"/api/tender-bids/{world.bids[key]}/documents", pdf),
        ("DELETE", f"/api/tender-bids/{world.bids[key]}", {}),
        ("POST", f"/api/tender-packages/{world.packages[key]}/award",
         {"json": {"winning_bid_id": str(world.bids[key]), "budget_id": str(uuid4()), "budget_line_id": str(uuid4()),
                   "award_instructions": "x", "project_start_date": "2026-12-01", "contractor_start_date": "2026-12-01"}}),
    ]


# ── auth ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_anonymous_is_unauthorized_when_auth_enforced(world: World) -> None:
    for path in ["/api/v1/projects", "/api/v1/lots", "/api/v1/clients", "/api/v1/workspace/context",
                 "/api/v1/workspace/dashboard", *tender_reads(world, "ch_project")]:
        response = await call("GET", path)
        assert response.status_code == 401, path
        response = await call("GET", path, org=world.ch_slug)
        assert response.status_code == 401, f"org header must not authenticate: {path}"
    health = await call("GET", "/health")
    assert health.status_code == 200


@pytest.mark.asyncio
async def test_fallback_actor_when_auth_disabled_is_pinned_to_default_org(world: World, monkeypatch) -> None:
    monkeypatch.setattr(settings, "auth_enforced", False)
    context = (await call("GET", "/api/v1/workspace/context")).json()
    assert context["actor"]["id"] == str(world.users["ch_admin"])
    assert context["actor"]["is_fallback"] is True
    assert context["org"]["id"] == str(world.ch)
    assert [org["id"] for org in context["available_orgs"]] == [str(world.ch)]
    assert context["capabilities"]["org_switch"] is False
    projects = ids(await call("GET", "/api/v1/projects"))
    assert str(world.lots["ch_project"]) in projects
    assert not projects & {str(world.lots["ps_a"]), str(world.lots["ps_b"])}
    for path in ["/api/v1/projects", f"/api/tender-packages/{world.packages['ps_a']}"]:
        response = await call("GET", path, org=world.ps_slug)
        assert response.status_code == 401, path
    assert (await call("GET", f"/api/tender-packages/{world.packages['ps_a']}")).status_code == 404


@pytest.mark.asyncio
async def test_signed_in_user_is_used_even_when_auth_disabled(world: World, monkeypatch) -> None:
    monkeypatch.setattr(settings, "auth_enforced", False)
    assert ids(await call("GET", "/api/v1/projects", world.users["ps_member"])) == {str(world.lots["ps_a"])}


# ── Connection Homes (org-wide scope) ────────────────────────────────────────

@pytest.mark.asyncio
async def test_ch_member_without_project_rows_keeps_org_wide_access(world: World) -> None:
    staff = world.users["ch_staff"]
    projects = ids(await call("GET", "/api/v1/projects", staff))
    assert str(world.lots["ch_project"]) in projects and str(world.lots["ch_land"]) not in projects
    assert not projects & {str(world.lots["ps_a"]), str(world.lots["ps_b"])}
    lots = ids(await call("GET", "/api/v1/lots", staff))
    assert str(world.lots["ch_land"]) in lots and str(world.lots["ch_project"]) not in lots
    assert (await call("GET", "/api/v1/lots/timeline", staff)).status_code == 200
    for path in tender_reads(world, "ch_project"):
        assert (await call("GET", path, staff)).status_code == 200, path
    response = await call("PATCH", f"/api/tender-packages/{world.packages['ch_project']}", staff, json={"status": "sent"})
    assert response.status_code == 200, response.text
    assert (await call("GET", f"/api/v1/lots/{world.lots['ch_land']}", staff)).status_code == 200
    assert (await call("GET", f"/api/v1/lots/{world.lots['ps_a']}", staff)).status_code == 404


@pytest.mark.asyncio
async def test_ch_readonly_reads_but_cannot_write(world: World) -> None:
    readonly = world.users["ch_readonly"]
    assert str(world.lots["ch_project"]) in ids(await call("GET", "/api/v1/projects", readonly))
    response = await call("PATCH", f"/api/tender-packages/{world.packages['ch_project']}", readonly, json={"status": "sent"})
    assert response.status_code == 403


# ── Potterstone (assigned scope) ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_potterstone_assigned_member_sees_only_assigned_project(world: World) -> None:
    member = world.users["ps_member"]
    assert ids(await call("GET", "/api/v1/projects", member)) == {str(world.lots["ps_a"])}
    assert (await call("GET", f"/api/v1/lots/{world.lots['ps_a']}", member)).status_code == 200
    for key in ("ps_b", "ch_project", "ch_land"):
        assert (await call("GET", f"/api/v1/lots/{world.lots[key]}", member)).status_code == 404, key
    assert (await call("GET", "/api/v1/lots", member)).status_code == 403
    assert (await call("GET", "/api/v1/lots/timeline", member)).status_code == 403
    for path in tender_reads(world, "ps_a"):
        assert (await call("GET", path, member)).status_code == 200, path
    for key in ("ps_b", "ch_project", "orphan"):
        for path in tender_reads(world, key):
            assert (await call("GET", path, member)).status_code == 404, path


@pytest.mark.asyncio
async def test_potterstone_cannot_write_unassigned_or_other_org_tender_objects(world: World) -> None:
    member = world.users["ps_member"]
    for key in ("ps_b", "ch_project", "orphan"):
        for method, path, kwargs in tender_writes(world, key):
            response = await call(method, path, member, **kwargs)
            assert response.status_code == 404, f"{method} {path} -> {response.status_code}"
    for lot in ("ps_b", "ch_project"):
        for flag in ("hold", "cancel"):
            body = {"on_hold": True} if flag == "hold" else {"cancelled": True}
            response = await call("PATCH", f"/api/v1/lots/{world.lots[lot]}/{flag}", member, json=body)
            assert response.status_code == 404


@pytest.mark.asyncio
async def test_potterstone_editor_and_viewer_roles_on_assigned_project(world: World) -> None:
    package = world.packages["ps_a"]
    ok = await call("PATCH", f"/api/tender-packages/{package}", world.users["ps_member"], json={"status": "bids_in"})
    assert ok.status_code == 200, ok.text
    viewer = await call("PATCH", f"/api/tender-packages/{package}", world.users["ps_viewer"], json={"status": "sent"})
    assert viewer.status_code == 403
    assert (await call("GET", f"/api/tender-packages/{package}", world.users["ps_viewer"])).status_code == 200
    # Contractors are not org-owned: bids and Costbook awards stay with the legacy org.
    bid = await call("POST", f"/api/tender-packages/{package}/bids", world.users["ps_member"],
                     json={"contractor_id": str(world.contractor)})
    assert bid.status_code == 403
    _, path, kwargs = tender_writes(world, "ps_a")[-1]
    assert (await call("POST", path, world.users["ps_member"], **kwargs)).status_code == 403


@pytest.mark.asyncio
async def test_potterstone_member_without_assignments_gets_empty_lists(world: World) -> None:
    member = world.users["ps_unassigned"]
    assert ids(await call("GET", "/api/v1/projects", member)) == set()
    clients = (await call("GET", "/api/v1/clients", member)).json()
    assert clients["total"] == 0 and clients["items"] == []
    dashboard = (await call("GET", "/api/v1/workspace/dashboard", member)).json()
    assert dashboard["projects"]["total"] == 0
    assert dashboard["tenders"]["total"] == 0
    assert dashboard["otp_milestones"] is None and dashboard["rentals"] is None
    for path in tender_reads(world, "ps_a"):
        assert (await call("GET", path, member)).status_code == 404, path


@pytest.mark.asyncio
async def test_potterstone_tenant_admin_sees_all_org_projects_only(world: World) -> None:
    assert ids(await call("GET", "/api/v1/projects", world.users["ps_admin"])) == {
        str(world.lots["ps_a"]), str(world.lots["ps_b"])}
    assert (await call("GET", "/api/v1/lots", world.users["ps_admin"])).status_code == 403


@pytest.mark.asyncio
async def test_potterstone_blocked_from_legacy_ch_modules(world: World) -> None:
    for path in ["/api/contractors", "/api/v1/costbook/budgets", "/api/v1/users", "/api/rentals/units"]:
        response = await call("GET", path, world.users["ps_admin"])
        assert response.status_code == 403, path
    assert (await call("GET", "/api/contractor-categories", world.users["ps_member"])).status_code == 200


# ── org selection ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_superadmin_cross_org_requires_explicit_selection(world: World) -> None:
    superadmin = world.users["superadmin"]
    home = ids(await call("GET", "/api/v1/projects", superadmin))
    assert str(world.lots["ch_project"]) in home and str(world.lots["ps_a"]) not in home
    assert (await call("GET", f"/api/tender-packages/{world.packages['ps_a']}", superadmin)).status_code == 404
    for selector in (world.ps_slug, str(world.ps)):
        assert ids(await call("GET", "/api/v1/projects", superadmin, org=selector)) == {
            str(world.lots["ps_a"]), str(world.lots["ps_b"])}
    assert (await call("GET", f"/api/tender-packages/{world.packages['ps_b']}", superadmin, org=world.ps_slug)).status_code == 200
    download = await call("GET", f"/api/tender-documents/{world.documents['ps_a']}/content?org={world.ps_slug}", superadmin)
    assert download.status_code == 200
    assert (await call("GET", f"/api/v1/lots/{world.lots['ch_project']}", superadmin, org=world.ps_slug)).status_code == 404
    context = (await call("GET", "/api/v1/workspace/context", superadmin, org=world.ps_slug)).json()
    assert context["org"]["id"] == str(world.ps)
    assert {str(world.ch), str(world.ps)} <= {org["id"] for org in context["available_orgs"]}
    assert context["capabilities"]["land"] is False and context["capabilities"]["legacy_modules"] is False


@pytest.mark.asyncio
async def test_invalid_or_non_member_org_selection_is_rejected(world: World) -> None:
    assert (await call("GET", "/api/v1/projects", world.users["ch_staff"], org="no-such-org")).status_code == 404
    assert (await call("GET", "/api/v1/projects", world.users["ch_staff"], org=world.ps_slug)).status_code == 403
    assert (await call("GET", "/api/v1/projects", world.users["ps_member"], org=world.ch_slug)).status_code == 403
    context = (await call("GET", "/api/v1/workspace/context", world.users["ps_member"])).json()
    assert [org["id"] for org in context["available_orgs"]] == [str(world.ps)]
    assert context["capabilities"]["org_switch"] is False


# ── clients ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_clients_are_org_owned_and_cross_org_links_are_rejected(world: World, wired) -> None:
    staff = world.users["ch_staff"]
    rejected = await call("POST", "/api/v1/clients", staff, json={"display_name": "X", "org_id": str(world.ps)})
    assert rejected.status_code == 422
    cross_contact = await call("POST", "/api/v1/clients", staff,
                               json={"display_name": "X", "primary_contact_id": str(world.contacts["ps"])})
    assert cross_contact.status_code == 422
    created = await call("POST", "/api/v1/clients", staff,
                         json={"display_name": f"  Smith {world.sfx} ", "primary_contact_id": str(world.contacts["ch"])})
    assert created.status_code == 201, created.text
    ch_client = created.json()
    assert ch_client["org_id"] == str(world.ch) and ch_client["display_name"] == f"Smith {world.sfx}"
    assert ch_client["lifecycle_stage"] == "lead" and ch_client["primary_contact"]["id"] == str(world.contacts["ch"])
    duplicate = await call("POST", "/api/v1/clients", staff, json={"display_name": f"smith {world.sfx}"})
    assert duplicate.status_code == 201
    assert duplicate.json()["duplicate_name_count"] == 1

    ps_client = await call("POST", "/api/v1/clients", world.users["superadmin"], org=world.ps_slug,
                           json={"display_name": f"PS Client {world.sfx}"})
    assert ps_client.status_code == 201 and ps_client.json()["org_id"] == str(world.ps)
    ps_client_id = ps_client.json()["id"]

    link = await call("PUT", f"/api/v1/projects/{world.lots['ch_project']}/client", staff, json={"client_id": ch_client["id"]})
    assert link.status_code == 200, link.text
    assert (await call("PUT", f"/api/v1/projects/{world.lots['ch_land']}/client", staff,
                       json={"client_id": ch_client["id"]})).status_code == 422
    assert (await call("PUT", f"/api/v1/projects/{world.lots['ch_project']}/client", staff,
                       json={"client_id": ps_client_id})).status_code == 422
    assert (await call("PUT", f"/api/v1/projects/{world.lots['ps_a']}/client", staff,
                       json={"client_id": ch_client["id"]})).status_code == 404
    assert (await call("PUT", f"/api/v1/projects/{world.lots['ps_a']}/client", world.users["superadmin"], org=world.ps_slug,
                       json={"client_id": ch_client["id"]})).status_code == 422
    assert (await call("PUT", f"/api/v1/projects/{world.lots['ps_a']}/client", world.users["ps_member"],
                       json={"client_id": ps_client_id})).status_code == 403

    detail = (await call("GET", f"/api/v1/clients/{ch_client['id']}", staff)).json()
    assert [project["id"] for project in detail["projects"]] == [str(world.lots["ch_project"])]
    projects = (await call("GET", "/api/v1/projects", staff)).json()
    linked = next(item for item in projects if item["id"] == str(world.lots["ch_project"]))
    assert linked["client_id"] == ch_client["id"] and linked["client_name"] == f"Smith {world.sfx}"

    listed = (await call("GET", f"/api/v1/clients?q=smith {world.sfx}", staff)).json()
    assert listed["total"] == 2 and ps_client_id not in {item["id"] for item in listed["items"]}
    assert (await call("GET", f"/api/v1/clients/{ps_client_id}", staff)).status_code == 404
    assert (await call("PATCH", f"/api/v1/clients/{ps_client_id}", staff, json={"notes": "x"})).status_code == 404
    assert (await call("GET", f"/api/v1/clients/{ch_client['id']}", world.users["ps_admin"])).status_code == 404

    staged = await call("PATCH", f"/api/v1/clients/{ch_client['id']}", staff, json={"lifecycle_stage": "qualified"})
    assert staged.status_code == 200 and staged.json()["lifecycle_stage"] == "qualified"
    assert staged.json()["stage_changed_at"] != ch_client["stage_changed_at"]
    audit = (await sql(wired, "SELECT count(*) FROM core.audit_log WHERE table_name = 'clients' AND record_id = :id",
                       id=ch_client["id"])).scalar_one()
    assert audit == 2
    assert (await call("PATCH", f"/api/v1/clients/{ch_client['id']}", world.users["ch_readonly"],
                       json={"notes": "x"})).status_code == 403
    assert (await call("POST", "/api/v1/clients", world.users["ps_member"], json={"display_name": "Nope"})).status_code == 403
    options = (await call("GET", "/api/v1/clients/contact-options", staff)).json()
    assert str(world.contacts["ch"]) in {item["id"] for item in options}
    assert str(world.contacts["ps"]) not in {item["id"] for item in options}

    # Assigned members only see clients of projects they can access.
    linked_ps = await call("PUT", f"/api/v1/projects/{world.lots['ps_a']}/client", world.users["ps_admin"],
                           json={"client_id": ps_client_id})
    assert linked_ps.status_code == 200, linked_ps.text
    assert {item["id"] for item in (await call("GET", "/api/v1/clients", world.users["ps_member"])).json()["items"]} == {ps_client_id}
    assert (await call("GET", "/api/v1/clients", world.users["ps_unassigned"])).json()["total"] == 0


@pytest.mark.asyncio
async def test_database_rejects_cross_org_links_even_without_the_api(world: World, wired) -> None:
    ps_client = (await sql(wired, "INSERT INTO core.clients (org_id, display_name, name_normalized) VALUES (:o, 'db', 'db') RETURNING id",
                           o=world.ps)).scalar_one()
    with pytest.raises(DBAPIError):
        await sql(wired, "UPDATE core.lots SET client_id = :c WHERE id = :l", c=ps_client, l=world.lots["ch_project"])
    with pytest.raises(DBAPIError):
        await sql(wired, "UPDATE core.clients SET org_id = :o WHERE id = :c", o=world.ch, c=ps_client)
    with pytest.raises(DBAPIError):
        await sql(wired, "INSERT INTO core.clients (org_id, display_name, name_normalized, primary_contact_id)"
                         " VALUES (:o, 'db2', 'db2', :c)", o=world.ps, c=world.contacts["ch"])


# ── dashboard and rentals ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_dashboard_is_org_scoped(world: World) -> None:
    dashboard = (await call("GET", "/api/v1/workspace/dashboard", world.users["ch_admin"])).json()
    tender_lots = {item["lot_id"] for item in dashboard["tenders"]["items"]}
    assert str(world.lots["ch_project"]) in tender_lots
    assert not tender_lots & {str(world.lots["ps_a"]), str(world.lots["ps_b"])}
    assert dashboard["otp_milestones"] is not None and dashboard["rentals"] is not None
    ps = (await call("GET", "/api/v1/workspace/dashboard", world.users["ps_member"])).json()
    assert ps["projects"]["total"] == 1
    assert {item["lot_id"] for item in ps["tenders"]["items"]} == {str(world.lots["ps_a"])}
    assert ps["otp_milestones"] is None and ps["rentals"] is None


@pytest.mark.asyncio
async def test_rentals_overview_limited_to_legacy_org(world: World) -> None:
    overview = await call("GET", "/api/v1/workspace/rentals-overview", world.users["ch_admin"])
    assert overview.status_code == 200, overview.text
    body = overview.json()
    assert body["occupancy"] is None and body["rent_collected"] is None
    assert isinstance(body["properties"], int) and isinstance(body["units"], int)
    assert (await call("GET", "/api/v1/workspace/rentals-overview", world.users["ch_staff"])).status_code == 403
    assert (await call("GET", "/api/v1/workspace/rentals-overview", world.users["ps_rentals_perm"])).status_code == 403
    assert (await call("GET", "/api/v1/workspace/rentals-overview", world.users["superadmin"], org=world.ps_slug)).status_code == 403


# ── users ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_invite_creates_default_org_membership(world: World, wired, monkeypatch) -> None:
    sent: list[str] = []

    async def fake_send(*, recipient: str, full_name: str) -> None:
        sent.append(recipient)

    monkeypatch.setattr(users_router, "send_user_invite", fake_send)
    email = f"invitee-{world.sfx}@officehub-tests.ca"
    response = await call("POST", "/api/v1/users/invite", world.users["ch_admin"], json={
        "first_name": "In", "last_name": "Vitee", "email": email, "role": "staff", "permissions": {}})
    assert response.status_code == 200, response.text
    assert sent == [email]
    role = (await sql(wired, "SELECT m.role FROM core.user_org_memberships m JOIN core.users u ON u.id = m.user_id"
                             " WHERE u.email = :e AND m.org_id = :o", e=email, o=world.ch)).scalar_one()
    assert role == "member"
