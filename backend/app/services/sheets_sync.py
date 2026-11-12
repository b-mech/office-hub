from __future__ import annotations

from datetime import date
from datetime import datetime
import logging
import os
import re
from typing import Any
from typing import Iterable
from uuid import UUID

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from sqlalchemy import bindparam
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.addresses import normalize_address
from app.core.config import settings
from app.services.financing import activate_from_construction_stage
from app.services.financing import get_or_create_stage_target
from app.services.financing import normalize_lender_type
from app.services.financing import upsert_stage_row


logger = logging.getLogger(__name__)

SHEET_ID = "1fzjmXSzvRFLNn1kq6ia-5Ly-AqGjxCKfZtWQKF1mj24"
STAGE_TAB_GID = "2088320803"
SHEETS_READONLY_SCOPE = "https://www.googleapis.com/auth/spreadsheets.readonly"
SYNC_CONFLICT = "SYNC_CONFLICT"
DEFAULT_BANK_COLUMN = "F"
BANK_HEADER_HINTS = ("banker", "bank", "nicholas", "lender")
UNCERTAIN_LENDER_RE = re.compile(
    r"\?\?|\A\?+\Z|^\s*-->|\bletter from realtor\b|\bto confirm\b",
    re.IGNORECASE,
)
EXCEL_ERROR_RE = re.compile(
    r"^#(?:REF|N/?A|VALUE|NAME|DIV/0|NULL|NUM|GETTING_DATA)!?$",
    re.IGNORECASE,
)
JUNK_ADDRESS_RE = re.compile(
    r"""
    ^(?:
        legend\b
      | preproduction\s+planning
      | \d+\s*\.?\s*$
      | \d+\s*[-–]\s*(fully\s+confirmed|nicholas\s+suggestion|robert\s+agreed)\b
    )
    | \badd\s+\d+\s*\?+
    | \bstatus\s+options\b
    | \bcolumn\s+[a-z]\s+banker\b
    """,
    re.IGNORECASE | re.VERBOSE,
)
# Canonical lenders for sheet-sync facility/lender UUID wiring.
# Never retarget or merge the duplicate Pro Auto lender.
CANONICAL_LENDER_IDS = {
    "PRO": UUID("52642c0d-3af6-4d23-a3bd-734e84585ea1"),
    "SCU": UUID("18c6d406-231c-41d9-8541-ef0044cba2d3"),
}
DUPLICATE_PRO_AUTO_LENDER_ID = UUID("eda3a4b0-d772-4dd3-92aa-8e7529194284")


def _default_bank_column() -> str:
    value = getattr(settings, "sheet_sync_bank_column", DEFAULT_BANK_COLUMN)
    return str(value or DEFAULT_BANK_COLUMN).strip().upper() or DEFAULT_BANK_COLUMN


def column_letter_to_index(letter: str) -> int:
    raw = (letter or "").strip().upper()
    if not re.fullmatch(r"[A-Z]+", raw):
        raise ValueError(f"Invalid sheet column letter: {letter!r}")
    index = 0
    for char in raw:
        index = index * 26 + (ord(char) - 64)
    return index - 1


def looks_like_bank_header(header: str | None) -> bool:
    text = re.sub(r"\s+", " ", (header or "").strip().casefold())
    return bool(text) and any(hint in text for hint in BANK_HEADER_HINTS)


def is_uncertain_lender(value: str | None) -> bool:
    text = (value or "").strip()
    if not text:
        return False
    return bool(UNCERTAIN_LENDER_RE.search(text))


def canonical_lender_id(lender_type: str | None) -> UUID | None:
    """Return the canonical lender UUID for a confirmed lender_type, if any."""
    if not lender_type:
        return None
    return CANONICAL_LENDER_IDS.get(str(lender_type).strip().upper())


def is_plausible_street_address(address: str | None) -> bool:
    """Return whether an Address-column value looks like a real civic address.

    Rejects Excel errors, legend/instruction text, and rows with no street
    number and street name. Notes on a real address (``??``, SPEC, dates) are
    allowed.
    """
    text = (address or "").strip()
    if not text:
        return False
    compact = re.sub(r"\s+", "", text)
    if EXCEL_ERROR_RE.match(text) or EXCEL_ERROR_RE.match(compact):
        return False
    if JUNK_ADDRESS_RE.search(text):
        return False
    normalized = normalize_address(text)
    if not normalized.street_number or not normalized.street_name:
        return False
    if not re.search(r"[A-Za-z]", normalized.street_name):
        return False
    return True


def classify_sheet_lender(raw: str | None) -> tuple[str, str | None, str]:
    """Return (banker_raw, lender_type, kind) for a column-F value.

    kind is one of: blank, uncertain, confirmed.
    Uncertain values (including ``??`` text that happens to contain SCU) leave
    lender_type null rather than guessing. Confirmed Pro Auto / ProAuto map to PRO.
    """
    text = (raw or "").strip()
    if not text:
        return "", None, "blank"
    if is_uncertain_lender(text):
        return text, None, "uncertain"
    return text, normalize_lender_type(text), "confirmed"


def resolve_lender_fields(
    incoming_raw: str | None,
    *,
    existing_raw: str | None = None,
    existing_type: str | None = None,
) -> dict[str, Any]:
    banker_raw, lender_type, kind = classify_sheet_lender(incoming_raw)
    existing_raw_text = (existing_raw or "").strip() or None
    existing_type_text = (existing_type or "").strip() or None
    has_existing = bool(existing_raw_text or existing_type_text)

    def _fields(
        *,
        banker_raw: str | None,
        lender_type: str | None,
        kind: str,
        resolution: str,
        changed: bool,
    ) -> dict[str, Any]:
        return {
            "banker_raw": banker_raw,
            "lender_type": lender_type,
            "lender_id": canonical_lender_id(lender_type),
            "kind": kind,
            "resolution": resolution,
            "changed": changed,
        }

    if kind != "confirmed":
        if has_existing:
            return _fields(
                banker_raw=existing_raw_text,
                lender_type=existing_type_text,
                kind=kind,
                resolution="preserved",
                changed=False,
            )
        if kind == "uncertain":
            return _fields(
                banker_raw=banker_raw,
                lender_type=None,
                kind=kind,
                resolution="lender_to_confirm",
                changed=True,
            )
        return _fields(
            banker_raw=None,
            lender_type=None,
            kind=kind,
            resolution="blank",
            changed=False,
        )

    changed = (banker_raw or None) != existing_raw_text or (lender_type or None) != existing_type_text
    return _fields(
        banker_raw=banker_raw,
        lender_type=lender_type,
        kind=kind,
        resolution="updated" if changed else "unchanged",
        changed=changed,
    )


def resolve_sheet_sync_options(
    *,
    query_dry_run: bool | None = None,
    query_delete_missing: bool | None = None,
    query_address_keys: list[str] | None = None,
    query_bank_column: str | None = None,
    body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Merge query/body flags. API default for dry_run is True.

    Explicit query params win over a body field; omitted query params fall back
    to the body, then to defaults. delete_missing defaults to False.
    """
    payload = body or {}

    def _pick(query_value: Any, key: str, default: Any) -> Any:
        if query_value is not None:
            return query_value
        if key in payload and payload[key] is not None:
            return payload[key]
        return default

    address_keys = _pick(query_address_keys, "address_keys", None)
    if isinstance(address_keys, str):
        address_keys = [address_keys]
    if address_keys is not None:
        address_keys = [str(item).strip() for item in address_keys if str(item).strip()]

    bank_column = _pick(query_bank_column, "bank_column", None)
    if bank_column:
        bank_column = str(bank_column).strip().upper()
    else:
        bank_column = _default_bank_column()

    return {
        "dry_run": bool(_pick(query_dry_run, "dry_run", True)),
        "delete_missing": bool(_pick(query_delete_missing, "delete_missing", False)),
        "address_keys": address_keys or None,
        "bank_column": bank_column,
    }


def _value(row: dict[str, str], *keys: str) -> str | None:
    lowered = {key.lower().strip(): value for key, value in row.items() if key is not None}
    for key in keys:
        value = lowered.get(key.lower().strip())
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def _stage_value(row: dict[str, str]) -> str:
    explicit = _value(row, "stage_clean", "Stage Clean", "stage_raw", "Stage")
    if explicit:
        return explicit.upper()

    for key, value in row.items():
        normalized_key = re.sub(r"\s+", " ", str(key).strip().upper())
        if "LAST UPDATE" in normalized_key and str(value).strip():
            return str(value).strip().upper()

    return "NA"


def _has_values(row: dict[str, str]) -> bool:
    return any(str(value).strip() for value in row.values())


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    cleaned = str(value).strip()
    # Unwrap markdown/asterisk (and underscore) wrappers, including **date**.
    cleaned = re.sub(r"^[*_]+|[*_]+$", "", cleaned).strip()
    cleaned = cleaned.replace("*", "").replace("_", " ").strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    # "February 18,2026" and "February 18 ,2026" -> "February 18, 2026"
    cleaned = re.sub(r"\s*,\s*", ", ", cleaned)
    if not cleaned:
        return None
    for fmt in (
        "%Y-%m-%d",
        "%m/%d/%Y",
        "%m/%d/%y",
        "%d/%m/%Y",
        "%B %d, %Y",
        "%b %d, %Y",
        "%B %d %Y",
        "%b %d %Y",
        "%d-%b-%Y",
        "%d-%b-%y",
    ):
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue
    return None


def _header_row_index(values: list[list[Any]]) -> int:
    for index, row in enumerate(values):
        normalized = {str(value).strip().lower() for value in row}
        if "address_key" in normalized and "address" in normalized:
            return index
    return 0


def column_cell(row: list[Any], index: int) -> str:
    if index < 0 or index >= len(row):
        return ""
    value = row[index]
    if value is None:
        return ""
    return str(value).strip()


def _row_to_named(headers: list[str], row: list[Any]) -> dict[str, str]:
    """Map unique header names to values. Duplicate headers keep the first value.

    Banker must never be read from this mapping in the production table parser;
    use the positional bank column instead.
    """
    named: dict[str, str] = {}
    for index, header in enumerate(headers):
        key = str(header).strip()
        if not key or key in named:
            continue
        named[key] = column_cell(row, index)
    # Preserve original padded length for headers that exist beyond the row.
    for header in headers:
        key = str(header).strip()
        named.setdefault(key, "")
    return named


def _parsed_row_from_named(
    source: dict[str, str],
    *,
    row_number: int,
    banker_raw: str | None,
) -> dict[str, Any] | None:
    if not _has_values(source):
        return None
    address = _value(source, "Address", "address", "address_raw", "address_key")
    if not address or not is_plausible_street_address(address):
        return None
    possession_raw = _value(source, "Client Possession", "possession_date")
    return {
        "row_number": row_number,
        "address_raw": address,
        "address_key": _value(source, "address_key", "Address Key") or "",
        "canonical_key": normalize_address(address).canonical_key,
        "banker_raw": banker_raw,
        "sold_or_spec": _value(source, "Sold or Spec", "sold_or_spec"),
        "stage_clean": _stage_value(source),
        "client_name": _value(source, "Client Name", "client_name"),
        "build_start": _parse_date(_value(source, "Build Start", "build_start")),
        "possession_date": _parse_date(possession_raw),
        "possession_date_locked": "**" in (possession_raw or ""),
    }


def _parse_stage_rows(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    """Parse already-named row dicts (unit tests / diagnostics).

    This path is not used for production sheet sync; banker is not inferred
    from a positional column here.
    """
    parsed_rows: list[dict[str, Any]] = []
    for index, source in enumerate(rows, start=2):
        parsed = _parsed_row_from_named(
            source,
            row_number=index,
            banker_raw=_value(source, "banker_raw", "Banker", "banker"),
        )
        if parsed:
            parsed_rows.append(parsed)
    return parsed_rows


def _parse_stage_table(
    values: list[list[Any]],
    *,
    bank_column: str | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Parse a raw sheet matrix, reading banker from a positional column (default F).

    Never falls back to column E (or any other column) when the bank column is
    blank, missing, or oddly headed.
    """
    warnings: list[str] = []
    if not values:
        return [], warnings

    header_index = _header_row_index(values)
    headers = [str(header).strip() for header in values[header_index]]
    column = (bank_column or _default_bank_column()).strip().upper() or DEFAULT_BANK_COLUMN
    bank_index = column_letter_to_index(column)
    bank_header = headers[bank_index] if bank_index < len(headers) else ""
    if not looks_like_bank_header(bank_header):
        warning = (
            f"Sheet column {column} header {bank_header!r} does not look like the bank column; "
            "banker will still be read from that column and will not fall back to column E"
        )
        logger.warning(warning)
        warnings.append(warning)

    parsed_rows: list[dict[str, Any]] = []
    for offset, raw_row in enumerate(values[header_index + 1 :], start=header_index + 2):
        source = _row_to_named(headers, raw_row)
        parsed = _parsed_row_from_named(
            source,
            row_number=offset,
            banker_raw=column_cell(raw_row, bank_index),
        )
        if parsed:
            parsed["bank_column"] = column
            parsed["bank_header"] = bank_header
            parsed_rows.append(parsed)
    return parsed_rows, warnings


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


def _allowlist_candidates(row: dict[str, Any]) -> set[str]:
    candidates: set[str] = set()
    for value in (row.get("canonical_key"), row.get("address_raw"), row.get("address_key")):
        text = (value or "").strip()
        if not text:
            continue
        candidates.add(text.casefold())
        candidates.add(normalize_address(text).canonical_key.casefold())
    return candidates


def _normalize_allowlist(address_keys: Iterable[str] | None) -> set[str] | None:
    if not address_keys:
        return None
    allowed: set[str] = set()
    for value in address_keys:
        text = (value or "").strip()
        if not text:
            continue
        allowed.add(text.casefold())
        allowed.add(normalize_address(text).canonical_key.casefold())
    return allowed or None


def _row_allowed(row: dict[str, Any], allowed: set[str] | None) -> bool:
    if allowed is None:
        return True
    return bool(_allowlist_candidates(row) & allowed)


async def _fetch_sheet_values() -> list[list[Any]]:
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
    return values_response.get("values", []) or []


async def _fetch_rows() -> list[dict[str, str]]:
    """Compatibility helper for diagnostics: named cells, banker still from column F."""
    values = await _fetch_sheet_values()
    rows, _warnings = _parse_stage_table(values)
    return [
        {
            "Address": row["address_raw"],
            "address_raw": row["address_raw"],
            "address_key": row.get("address_key") or "",
            "banker_raw": row.get("banker_raw") or "",
            "Sold or Spec": row.get("sold_or_spec") or "",
            "stage_clean": row.get("stage_clean") or "",
            "Client Name": row.get("client_name") or "",
            "Build Start": str(row["build_start"] or ""),
            "Client Possession": str(row["possession_date"] or ""),
        }
        for row in rows
    ]


async def _load_existing_sync_rows(db: AsyncSession) -> dict[str, dict[str, Any]]:
    result = await db.execute(
        text(
            """
            SELECT
                address_raw,
                banker_raw,
                lender_type,
                property_id,
                build_group_id,
                sold_or_spec,
                stage_clean
            FROM documents.construction_stage_sync
            """
        )
    )
    existing: dict[str, dict[str, Any]] = {}
    for row in result.mappings().all():
        payload = dict(row)
        address = (payload.get("address_raw") or "").strip()
        if not address:
            continue
        existing[address] = payload
        existing.setdefault(normalize_address(address).canonical_key, payload)
    return existing


def _existing_for_row(row: dict[str, Any], existing: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    for key in (row.get("address_raw"), row.get("canonical_key")):
        if key and key in existing:
            return existing[key]
    return None


def _sync_conflicts_payload(parsed_rows: list[dict[str, Any]], conflict_keys: set[str]) -> list[dict[str, Any]]:
    return [
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
    ]


def _unique_existing_rows(existing: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    rows: list[dict[str, Any]] = []
    for payload in existing.values():
        address = (payload.get("address_raw") or "").strip()
        if not address or address in seen:
            continue
        seen.add(address)
        rows.append(payload)
    return rows


def _junk_existing_items(existing: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for payload in _unique_existing_rows(existing):
        address = (payload.get("address_raw") or "").strip()
        if is_plausible_street_address(address):
            continue
        property_id = payload.get("property_id")
        items.append(
            {
                "kind": "junk_existing",
                "address_raw": address,
                "canonical_key": normalize_address(address).canonical_key,
                "property_id": str(property_id) if property_id else None,
                "banker_raw": payload.get("banker_raw"),
                "lender_type": payload.get("lender_type"),
            }
        )
    return items


def _as_uuid(value: Any) -> UUID | None:
    if value is None or value == "":
        return None
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        return None


async def _load_property_facilities(db: AsyncSession, property_id: UUID) -> list[dict[str, Any]]:
    result = await db.execute(
        text(
            """
            SELECT id, property_id, lot_id, lender_id, lender_type, lender_name, status
            FROM core.lender_facilities
            WHERE property_id = :property_id
            """
        ),
        {"property_id": property_id},
    )
    return [dict(row) for row in result.mappings().all()]


def plan_facility_lender_updates(
    facilities: list[dict[str, Any]],
    lender_type: str | None,
) -> list[dict[str, Any]]:
    """Plan facility lender_id writes for a confirmed PRO/SCU sync row.

    Fills a null lender_id with the canonical UUID when the facility type
    matches. Facilities already linked to the duplicate Pro Auto lender
    ``eda3a4b0-...`` are left untouched and recorded as preserved. Other
    existing lender_id values are not rewritten, and lender rows are never
    merged.
    """
    canonical = canonical_lender_id(lender_type)
    if not canonical or not lender_type:
        return []
    wanted_type = str(lender_type).strip().upper()
    planned: list[dict[str, Any]] = []
    for facility in facilities:
        facility_id = facility.get("id")
        if facility_id is None:
            continue
        facility_type = (facility.get("lender_type") or "").strip().upper()
        if facility_type and facility_type != wanted_type:
            continue
        current_id = _as_uuid(facility.get("lender_id"))
        if current_id == canonical:
            continue
        if current_id == DUPLICATE_PRO_AUTO_LENDER_ID:
            planned.append(
                {
                    "kind": "lender_id_preserved_duplicate",
                    "facility_id": str(facility_id),
                    "property_id": str(facility["property_id"]) if facility.get("property_id") else None,
                    "lender_type": wanted_type,
                    "existing_lender_id": str(current_id),
                    "canonical_lender_id": str(canonical),
                }
            )
            continue
        if current_id is not None:
            continue
        planned.append(
            {
                "kind": "set_lender_id",
                "facility_id": str(facility_id),
                "property_id": str(facility["property_id"]) if facility.get("property_id") else None,
                "lender_type": wanted_type,
                "lender_id": str(canonical),
                "existing_lender_id": None,
            }
        )
    return planned


async def _facility_lender_items(
    db: AsyncSession,
    *,
    property_id: Any,
    lender_type: str | None,
    dry_run: bool,
) -> list[dict[str, Any]]:
    resolved_property_id = _as_uuid(property_id)
    if resolved_property_id is None:
        return []
    facilities = await _load_property_facilities(db, resolved_property_id)
    planned = plan_facility_lender_updates(facilities, lender_type)
    if dry_run:
        return planned
    applied: list[dict[str, Any]] = []
    for item in planned:
        if item.get("kind") != "set_lender_id":
            applied.append(item)
            continue
        await db.execute(
            text(
                """
                UPDATE core.lender_facilities
                SET lender_id = :lender_id, updated_at = now()
                WHERE id = :id
                  AND lender_id IS NULL
                """
            ),
            {"lender_id": item["lender_id"], "id": item["facility_id"]},
        )
        applied.append(item)
    return applied


def _manifest_item(kind: str, row: dict[str, Any], **extra: Any) -> dict[str, Any]:
    item = {
        "kind": kind,
        "address_raw": row.get("address_raw"),
        "canonical_key": row.get("canonical_key"),
        "row_number": row.get("row_number"),
    }
    item.update(extra)
    return item


def _result(
    *,
    synced: int,
    created_properties: int,
    stale_deleted: int,
    errors: list[str],
    parsed_rows: list[dict[str, Any]],
    conflict_keys: set[str],
    dry_run: bool,
    delete_missing: bool,
    warnings: list[str],
    manifest: list[dict[str, Any]],
    bank_column: str,
) -> dict[str, Any]:
    return {
        "synced": synced,
        "created_properties": created_properties,
        "stale_deleted": stale_deleted,
        "errors": errors,
        "sync_conflicts": _sync_conflicts_payload(parsed_rows, conflict_keys),
        "dry_run": dry_run,
        "delete_missing": delete_missing,
        "warnings": warnings,
        "manifest": manifest,
        "bank_column": bank_column,
    }


async def _missing_sync_addresses(db: AsyncSession, current_addresses: list[str]) -> list[str]:
    result = await db.execute(
        text(
            """
            SELECT address_raw
            FROM documents.construction_stage_sync
            WHERE address_raw NOT IN :current_addresses
            """
        ).bindparams(bindparam("current_addresses", expanding=True)),
        {"current_addresses": current_addresses},
    )
    return [row[0] for row in result.all()]


async def _delete_missing_rows(db: AsyncSession, current_addresses: list[str]) -> list[str]:
    result = await db.execute(
        text(
            """
            DELETE FROM documents.construction_stage_sync
            WHERE address_raw NOT IN :current_addresses
            RETURNING address_raw
            """
        ).bindparams(bindparam("current_addresses", expanding=True)),
        {"current_addresses": current_addresses},
    )
    return [row[0] for row in result.all()]


async def sync_from_sheet(
    db: AsyncSession,
    *,
    dry_run: bool | None = None,
    delete_missing: bool = False,
    address_keys: list[str] | None = None,
    bank_column: str | None = None,
) -> dict[str, Any]:
    """Sync construction stage rows from the tracker sheet.

    ``dry_run`` defaults to True (no writes). Existing callers that intend to
    write must pass ``dry_run=False`` explicitly. Missing-row deletes are off
    unless ``delete_missing=True``, and they are skipped when an address
    allowlist is in use.
    """
    if dry_run is None:
        dry_run = True

    column = (bank_column or _default_bank_column()).strip().upper() or DEFAULT_BANK_COLUMN
    values = await _fetch_sheet_values()
    parsed_rows, warnings = _parse_stage_table(values, bank_column=column)
    allowed = _normalize_allowlist(address_keys)
    selected = [row for row in parsed_rows if _row_allowed(row, allowed)]
    if allowed is not None and delete_missing:
        warning = (
            "delete_missing was requested with an address allowlist; "
            "deletes are skipped to avoid removing rows outside the targeted set"
        )
        logger.warning(warning)
        warnings.append(warning)
        delete_missing = False

    conflict_keys = _conflicting_stage_keys(selected)
    existing = await _load_existing_sync_rows(db)
    current_addresses = [row["address_raw"] for row in selected]
    manifest: list[dict[str, Any]] = []
    errors: list[str] = []
    synced = 0
    created_properties = 0
    stale_deleted = 0
    planned: list[dict[str, Any]] = []

    for source in selected:
        current = _existing_for_row(source, existing)
        lender = resolve_lender_fields(
            source.get("banker_raw"),
            existing_raw=(current or {}).get("banker_raw"),
            existing_type=(current or {}).get("lender_type"),
        )
        payload = {
            "address_raw": source["address_raw"],
            "banker_raw": lender["banker_raw"],
            "lender_type": lender["lender_type"],
            "lender_id": lender.get("lender_id"),
            "sold_or_spec": source["sold_or_spec"],
            "stage_clean": SYNC_CONFLICT
            if source["canonical_key"] in conflict_keys
            else source["stage_clean"],
            "client_name": source["client_name"],
            "build_start": source["build_start"],
            "possession_date": source["possession_date"],
            "possession_date_locked": source["possession_date_locked"],
            "row_number": source["row_number"],
            "canonical_key": source["canonical_key"],
            "lender_resolution": lender["resolution"],
            "lender_changed": lender["changed"],
        }
        is_insert = current is None
        if dry_run:
            try:
                property_id, _build_group_id, would_create = await get_or_create_stage_target(
                    db,
                    source["address_raw"],
                    create=False,
                    for_update=False,
                )
                would_activate = False
                if property_id:
                    would_activate = await activate_from_construction_stage(
                        db,
                        property_id=property_id,
                        address=source["address_raw"],
                        sold_or_spec=source.get("sold_or_spec"),
                        dry_run=True,
                    )
            except Exception as exc:
                reason = str(exc).splitlines()[0]
                errors.append(f"Row {source['row_number']}: {reason}")
                continue
            lender_id = lender.get("lender_id")
            manifest.append(
                _manifest_item(
                    "insert" if is_insert else "update",
                    source,
                    banker_raw=lender["banker_raw"],
                    lender_type=lender["lender_type"],
                    lender_id=str(lender_id) if lender_id else None,
                    lender_resolution=lender["resolution"],
                    lender_changed=lender["changed"],
                    sold_or_spec=source.get("sold_or_spec"),
                    stage_clean=payload["stage_clean"],
                )
            )
            if would_create:
                created_properties += 1
                manifest.append(_manifest_item("create_property", source))
            if would_activate:
                manifest.append(_manifest_item("activate", source, sold_or_spec=source.get("sold_or_spec")))
            facility_property_id = property_id or (current or {}).get("property_id")
            manifest.extend(
                await _facility_lender_items(
                    db,
                    property_id=facility_property_id,
                    lender_type=lender["lender_type"],
                    dry_run=True,
                )
            )
            synced += 1
            continue
        planned.append(payload)

    if dry_run:
        if delete_missing and current_addresses:
            stale = [
                address
                for address in await _missing_sync_addresses(db, current_addresses)
                if is_plausible_street_address(address)
            ]
            stale_deleted = len(stale)
            for address in stale:
                manifest.append(
                    {
                        "kind": "delete",
                        "address_raw": address,
                        "canonical_key": normalize_address(address).canonical_key,
                    }
                )
        manifest.extend(_junk_existing_items(existing))
        return _result(
            synced=synced,
            created_properties=created_properties,
            stale_deleted=stale_deleted,
            errors=errors,
            parsed_rows=selected,
            conflict_keys=conflict_keys,
            dry_run=True,
            delete_missing=delete_missing,
            warnings=warnings,
            manifest=manifest,
            bank_column=column,
        )

    async with db.begin():
        if delete_missing and current_addresses:
            # Never delete junk Address-column rows; they are reported as junk_existing.
            current_and_junk = list(current_addresses) + [
                (payload.get("address_raw") or "").strip()
                for payload in _unique_existing_rows(existing)
                if not is_plausible_street_address((payload.get("address_raw") or "").strip())
            ]
            deleted_addresses = await _delete_missing_rows(db, [addr for addr in current_and_junk if addr])
            stale_deleted = len(deleted_addresses)
            for address in deleted_addresses:
                manifest.append(
                    {
                        "kind": "delete",
                        "address_raw": address,
                        "canonical_key": normalize_address(address).canonical_key,
                    }
                )
        for payload in planned:
            try:
                async with db.begin_nested():
                    created, activated = await upsert_stage_row(
                        db,
                        payload,
                        return_activation=True,
                    )
                synced += 1
                lender_id = payload.get("lender_id")
                manifest.append(
                    _manifest_item(
                        "insert" if _existing_for_row(payload, existing) is None else "update",
                        payload,
                        banker_raw=payload.get("banker_raw"),
                        lender_type=payload.get("lender_type"),
                        lender_id=str(lender_id) if lender_id else None,
                        lender_resolution=payload.get("lender_resolution"),
                        lender_changed=payload.get("lender_changed"),
                        sold_or_spec=payload.get("sold_or_spec"),
                        stage_clean=payload.get("stage_clean"),
                    )
                )
                if created:
                    created_properties += 1
                    manifest.append(_manifest_item("create_property", payload))
                if activated:
                    manifest.append(
                        _manifest_item("activate", payload, sold_or_spec=payload.get("sold_or_spec"))
                    )
                current_row = _existing_for_row(payload, existing)
                facility_property_id = (current_row or {}).get("property_id")
                manifest.extend(
                    await _facility_lender_items(
                        db,
                        property_id=facility_property_id,
                        lender_type=payload.get("lender_type"),
                        dry_run=False,
                    )
                )
            except Exception as exc:
                logger.exception("Failed to sync construction stage row")
                reason = str(exc).splitlines()[0]
                errors.append(f"Row {payload['row_number']}: {reason}")

    manifest.extend(_junk_existing_items(existing))
    return _result(
        synced=synced,
        created_properties=created_properties,
        stale_deleted=stale_deleted,
        errors=errors,
        parsed_rows=selected,
        conflict_keys=conflict_keys,
        dry_run=False,
        delete_missing=delete_missing,
        warnings=warnings,
        manifest=manifest,
        bank_column=column,
    )
