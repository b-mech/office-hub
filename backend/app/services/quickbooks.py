from __future__ import annotations

import json
import os
import secrets
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.addresses import normalize_address
from app.core.config import settings
from app.models.sales import ChangeOrder

AUTH_URL = "https://appcenter.intuit.com/connect/oauth2"
TOKEN_URL = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"
SCOPE = "com.intuit.quickbooks.accounting"
_oauth_state: str | None = None


def authorization_url() -> str:
    global _oauth_state
    if not settings.qbo_client_id:
        raise ValueError("QBO_CLIENT_ID is not configured")
    _oauth_state = secrets.token_urlsafe(32)
    return f"{AUTH_URL}?{urlencode({'client_id': settings.qbo_client_id, 'scope': SCOPE, 'redirect_uri': settings.qbo_redirect_uri, 'response_type': 'code', 'state': _oauth_state})}"


async def handle_callback(code: str, state: str, realm_id: str) -> None:
    if not _oauth_state or state != _oauth_state:
        raise ValueError("QuickBooks OAuth state mismatch")
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(TOKEN_URL, data={"grant_type": "authorization_code", "code": code, "redirect_uri": settings.qbo_redirect_uri}, auth=(settings.qbo_client_id, settings.qbo_client_secret), headers={"Accept": "application/json"})
    response.raise_for_status()
    _save_token({**response.json(), "realm_id": realm_id, "obtained_at": datetime.now(timezone.utc).isoformat()})


async def create_invoice(db: AsyncSession, change_order_id: object) -> None:
    change_order = (
        await db.execute(
            select(ChangeOrder)
            .where(ChangeOrder.id == change_order_id)
            .options(selectinload(ChangeOrder.line_items))
        )
    ).scalar_one_or_none()
    if change_order is None or change_order.qb_invoice_id:
        return
    try:
        if change_order.qb_project_id and change_order.qb_customer_id:
            project, parent = {"Id": change_order.qb_project_id}, {"Id": change_order.qb_customer_id}
        else:
            project, parent = await _match_project(change_order.address)
        item_id = settings.qbo_change_order_item_id or await _default_service_item_id()
        description = "; ".join(item.description for item in change_order.line_items if item.description) or f"Change order {change_order.co_number or change_order.id}"
        payload = {
            "CustomerRef": {"value": project["Id"]},
            "PrivateNote": f"Office Hub change order {change_order.id}",
            "Line": [{"Amount": Decimal(change_order.total).quantize(Decimal('0.01')), "DetailType": "SalesItemLineDetail", "Description": description, "SalesItemLineDetail": {"ItemRef": {"value": item_id}}}],
        }
        result = await _request("POST", "/invoice", json_body=payload)
        invoice = result["Invoice"]
        change_order.qb_invoice_id = str(invoice["Id"])
        change_order.qb_invoice_status = "created"
        change_order.qb_project_id = str(project["Id"])
        change_order.qb_customer_id = str(parent["Id"])
        change_order.qb_sync_error = None
    except Exception as exc:
        change_order.qb_invoice_status = "synced_error"
        change_order.qb_sync_error = str(exc)[:1000]
    await db.commit()


async def retry_invoice(db: AsyncSession, change_order: ChangeOrder) -> None:
    change_order.qb_invoice_status = "not_created"
    change_order.qb_sync_error = None
    await db.commit()
    await create_invoice(db, change_order.id)


async def set_mapping_and_retry(db: AsyncSession, change_order: ChangeOrder, customer_id: str, project_id: str) -> None:
    change_order.qb_customer_id = customer_id.strip()
    change_order.qb_project_id = project_id.strip()
    await retry_invoice(db, change_order)


async def reconcile_open_invoices(db: AsyncSession) -> int:
    orders = list((await db.execute(select(ChangeOrder).where(ChangeOrder.qb_invoice_status == "created", ChangeOrder.qb_invoice_id.is_not(None)))).scalars())
    paid = 0
    for order in orders:
        try:
            result = await _request("GET", f"/invoice/{order.qb_invoice_id}")
            invoice = result["Invoice"]
            if Decimal(str(invoice.get("Balance", "0"))) == Decimal("0"):
                order.qb_invoice_status = "paid"
                paid += 1
        except Exception as exc:
            order.qb_sync_error = str(exc)[:1000]
    await db.commit()
    return paid


async def _match_project(address: str) -> tuple[dict[str, Any], dict[str, Any]]:
    customers = await _customers()
    target = normalize_address(address).canonical_key
    by_id = {str(item["Id"]): item for item in customers}
    matches = []
    for customer in customers:
        if not customer.get("Job") and not customer.get("ParentRef"):
            continue
        candidates = [customer.get("DisplayName", ""), customer.get("FullyQualifiedName", "")]
        bill = customer.get("BillAddr") or {}
        candidates.extend(str(bill.get(key, "")) for key in ("Line1", "Line2", "City"))
        if any(normalize_address(value).canonical_key == target for value in candidates if value):
            matches.append(customer)
    if len(matches) != 1:
        raise ValueError(f"Expected one QuickBooks project match for {address}; found {len(matches)}")
    project = matches[0]
    parent_id = str((project.get("ParentRef") or {}).get("value", ""))
    parent = by_id.get(parent_id)
    if parent is None:
        raise ValueError("Matched QuickBooks project has no available parent customer")
    return project, parent


async def _customers() -> list[dict[str, Any]]:
    cache_path = Path(settings.qbo_customer_cache_file).expanduser()
    if cache_path.exists() and datetime.now(timezone.utc) - datetime.fromtimestamp(cache_path.stat().st_mtime, timezone.utc) < timedelta(hours=12):
        return json.loads(cache_path.read_text()).get("customers", [])
    result = await _query("select * from Customer maxresults 1000")
    customers = result.get("QueryResponse", {}).get("Customer", [])
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps({"customers": customers}))
    return customers


async def _default_service_item_id() -> str:
    result = await _query("select * from Item where Active = true maxresults 1000")
    items = result.get("QueryResponse", {}).get("Item", [])
    item = next((item for item in items if item.get("Type") == "Service"), None)
    if item is None:
        raise ValueError("No active QuickBooks service item found; configure QBO_CHANGE_ORDER_ITEM_ID")
    return str(item["Id"])


async def _query(query: str) -> dict[str, Any]:
    return await _request("GET", "/query", params={"query": query})


async def _request(method: str, path: str, *, params: dict[str, str] | None = None, json_body: dict[str, Any] | None = None) -> dict[str, Any]:
    token = await _access_token()
    base = "https://sandbox-quickbooks.api.intuit.com" if settings.qbo_environment == "sandbox" else "https://quickbooks.api.intuit.com"
    url = f"{base}/v3/company/{token['realm_id']}{path}"
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.request(method, url, params=params, content=_encode_json(json_body) if json_body is not None else None, headers={"Authorization": f"Bearer {token['access_token']}", "Accept": "application/json", "Content-Type": "application/json"})
    response.raise_for_status()
    return response.json()


async def _access_token() -> dict[str, Any]:
    token = _load_token()
    obtained = datetime.fromisoformat(token["obtained_at"])
    if datetime.now(timezone.utc) < obtained + timedelta(seconds=int(token.get("expires_in", 3600)) - 120):
        return token
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(TOKEN_URL, data={"grant_type": "refresh_token", "refresh_token": token["refresh_token"]}, auth=(settings.qbo_client_id, settings.qbo_client_secret), headers={"Accept": "application/json"})
    response.raise_for_status()
    refreshed = {**response.json(), "realm_id": token["realm_id"], "obtained_at": datetime.now(timezone.utc).isoformat()}
    _save_token(refreshed)
    return refreshed


def _load_token() -> dict[str, Any]:
    path = Path(settings.qbo_token_file).expanduser()
    if not path.exists():
        raise ValueError("QuickBooks is not connected")
    return json.loads(path.read_text())


def _save_token(token: dict[str, Any]) -> None:
    path = Path(settings.qbo_token_file).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(token))
    os.chmod(path, 0o600)


def _encode_json(value: dict[str, Any]) -> str:
    markers: dict[str, str] = {}

    def prepare(item: object) -> object:
        if isinstance(item, Decimal):
            marker = f"__decimal_{len(markers)}__"
            markers[marker] = format(item, "f")
            return marker
        if isinstance(item, dict):
            return {key: prepare(child) for key, child in item.items()}
        if isinstance(item, list):
            return [prepare(child) for child in item]
        return item

    encoded = json.dumps(prepare(value), separators=(",", ":"))
    for marker, decimal_text in markers.items():
        encoded = encoded.replace(json.dumps(marker), decimal_text)
    return encoded
