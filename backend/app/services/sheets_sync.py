from __future__ import annotations

from datetime import date
from datetime import datetime
import json
import os
import re
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from sqlalchemy import bindparam
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.addresses import normalize_address
from app.services.financing import normalize_lender_type
from app.services.financing import upsert_stage_row


SHEET_ID = "1fzjmXSzvRFLNn1kq6ia-5Ly-AqGjxCKfZtWQKF1mj24"
STAGE_TAB_GID = "2088320803"
SHEETS_READONLY_SCOPE = "https://www.googleapis.com/auth/spreadsheets.readonly"
SYNC_CONFLICT = "SYNC_CONFLICT"


async def sync_from_sheet(db: AsyncSession) -> dict[str, Any]:
    rows = await _fetch_rows()
    parsed_rows = _parse_stage_rows(rows)
    conflict_keys = _conflicting_stage_keys(parsed_rows)
    synced = 0
    created_properties = 0
    stale_deleted = 0
    errors: list[str] = []

    async with db.begin():
        current_addresses = [row["address_raw"] for row in parsed_rows]
        if current_addresses:
            delete_result = await db.execute(
                text(
                    """
                    DELETE FROM documents.construction_stage_sync
                    WHERE address_raw NOT IN :current_addresses
                    """
                ).bindparams(bindparam("current_addresses", expanding=True)),
                {"current_addresses": current_addresses},
            )
            stale_deleted = delete_result.rowcount or 0
        for source in parsed_rows:
            try:
                address = source["address_raw"]
                banker = source["banker_raw"]
                created = await upsert_stage_row(
                    db,
                    {
                        "address_raw": address,
                        "banker_raw": banker,
                        "lender_type": normalize_lender_type(banker),
                        "sold_or_spec": source["sold_or_spec"],
                        "stage_clean": SYNC_CONFLICT
                        if source["canonical_key"] in conflict_keys
                        else source["stage_clean"],
                        "client_name": source["client_name"],
                        "build_start": source["build_start"],
                        "possession_date": source["possession_date"],
                    },
                )
                synced += 1
                if created:
                    created_properties += 1
            except Exception as exc:
                errors.append(f"Row {source['row_number']}: {exc}")

    return {
        "synced": synced,
        "created_properties": created_properties,
        "stale_deleted": stale_deleted,
        "errors": errors,
        "sync_conflicts": [
            {
                "canonical_address_key": key,
                "rows": [
                    {
                        "row_number": row["row_number"],
                        "address_raw": row["address_raw"],
                        "sold_or_spec": row["sold_or_spec"],
                        "stage_clean": row["stage_clean"],
                    }
                    for row in parsed_rows
                    if row["canonical_key"] == key
                ],
            }
            for key in sorted(conflict_keys)
        ],
    }


def _parse_stage_rows(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    parsed_rows: list[dict[str, Any]] = []
    for index, source in enumerate(rows, start=2):
        if not _has_values(source):
            continue
        address = _value(source, "Address", "address", "address_raw", "address_key")
        if not address:
            continue
        banker = _value(source, "Banker", "banker")
        parsed_rows.append(
            {
                "row_number": index,
                "address_raw": address,
                "canonical_key": normalize_address(address).canonical_key,
                "banker_raw": banker,
                "sold_or_spec": _value(source, "Sold or Spec", "sold_or_spec"),
                "stage_clean": _stage_value(source),
                "client_name": _value(source, "Client Name", "client_name"),
                "build_start": _parse_date(_value(source, "Build Start", "build_start")),
                "possession_date": _parse_date(_value(source, "Client Possession", "possession_date")),
            }
        )
    return parsed_rows


def _conflicting_stage_keys(rows: list[dict[str, Any]]) -> set[str]:
    by_key: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_key.setdefault(row["canonical_key"], []).append(row)

    conflict_keys: set[str] = set()
    for key, group in by_key.items():
        if len(group) < 2:
            continue
        stages = {row["stage_clean"] for row in group if row["stage_clean"] and row["stage_clean"] != "NA"}
        if len(stages) <= 1:
            continue
        conflict_keys.add(key)
    return conflict_keys


async def _fetch_rows() -> list[dict[str, str]]:
    if not settings.google_oauth_client_secret_path:
        raise RuntimeError("GOOGLE_OAUTH_CLIENT_SECRET_PATH is not configured")

    token_path = os.path.expanduser(settings.google_oauth_token_path)
    client_secret_path = os.path.expanduser(settings.google_oauth_client_secret_path)
    creds = None

    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, [SHEETS_READONLY_SCOPE])

    # On first run with no token file, this will open a browser window for Google sign-in.
    # The token is saved afterward and reused on every subsequent call.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(client_secret_path, [SHEETS_READONLY_SCOPE])
            creds = flow.run_local_server(port=0)
        os.makedirs(os.path.dirname(token_path), exist_ok=True)
        with open(token_path, "w") as token_file:
            token_file.write(creds.to_json())

    service = build("sheets", "v4", credentials=creds, cache_discovery=False)
    metadata = (
        service.spreadsheets()
        .get(spreadsheetId=SHEET_ID, fields="sheets(properties(sheetId,title))")
        .execute()
    )
    sheet_title = None
    for sheet in metadata.get("sheets", []):
        properties = sheet.get("properties", {})
        if properties.get("sheetId") == int(STAGE_TAB_GID):
            sheet_title = properties.get("title")
            break
    if not sheet_title:
        raise RuntimeError(f"Sheet tab with gid {STAGE_TAB_GID} was not found")

    values_response = (
        service.spreadsheets()
        .values()
        .get(
            spreadsheetId=SHEET_ID,
            range=f"'{sheet_title}'",
        )
        .execute()
    )
    values = values_response.get("values", [])
    if not values:
        return []

    header_index = _header_row_index(values)
    headers = [str(header).strip() for header in values[header_index]]
    rows: list[dict[str, str]] = []
    for row in values[header_index + 1 :]:
        padded = [str(value) for value in row] + [""] * max(0, len(headers) - len(row))
        source = dict(zip(headers, padded[: len(headers)]))
        if _has_values(source):
            rows.append(source)
    return rows


def _header_row_index(values: list[list[str]]) -> int:
    for index, row in enumerate(values):
        normalized = {str(value).strip().lower() for value in row}
        if "address_key" in normalized and "address" in normalized:
            return index
    return 0


def _value(row: dict[str, str], *keys: str) -> str | None:
    lowered = {key.lower().strip(): value for key, value in row.items() if key is not None}
    for key in keys:
        value = lowered.get(key.lower().strip())
        if value is not None and value.strip():
            return value.strip()
    return None


def _stage_value(row: dict[str, str]) -> str:
    explicit = _value(row, "stage_clean", "Stage Clean", "stage_raw", "Stage")
    if explicit:
        return explicit.upper()

    for key, value in row.items():
        normalized_key = re.sub(r"\s+", " ", key.strip().upper())
        if "LAST UPDATE" in normalized_key and value.strip():
            return value.strip().upper()

    return "NA"


def _has_values(row: dict[str, str]) -> bool:
    return any(str(value).strip() for value in row.values())


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    cleaned = re.sub(r"^\*+|\*+$", "", value.strip()).strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%d/%m/%Y", "%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue
    return None
