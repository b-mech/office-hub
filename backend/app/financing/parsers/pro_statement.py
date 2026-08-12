from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.financing.engines.pro import money


MONEY_PATTERN = re.compile(r"-?\$?\s*\.?[\d,]+\.\d{2}")
SCHEDULE_MONEY = r"-?\$?\s*(?:\.?[\d,]+\.\d{2}|\.?0{1,2})"
SCHEDULE_ROW_PATTERN = re.compile(
    r"^(?P<date>\d{1,2}/\d{1,2}/\d{2,4})\s+"
    r"(?P<days>\d+)\s+"
    r"(?P<pmt>\S+)\s+"
    rf"(?P<payment>{SCHEDULE_MONEY})\s+"
    r"(?P<rate>\d+(?:\.\d+)?)\s*%?\s+"
    rf"(?P<interest>{SCHEDULE_MONEY})\s+"
    rf"(?P<principal>{SCHEDULE_MONEY})\s+"
    rf"(?P<balance>{SCHEDULE_MONEY})\s+"
    rf"(?P<prepay>{SCHEDULE_MONEY})"
    rf"(?:\s+(?P<acc_int>{SCHEDULE_MONEY}))?"
    r"(?:\s+(?P<reference>.*))?$"
)


@dataclass(frozen=True)
class ParsedProDraw:
    txn_date: date
    amount: Decimal
    reference: str | None


@dataclass(frozen=True)
class ParsedProFacilityStatement:
    property_name: str
    original_advance_date: date
    original_advance_amount: Decimal
    annual_rate: Decimal
    draws: list[ParsedProDraw]
    period_end_date: date
    period_end_balance: Decimal
    validation_errors: list[str]


def parse_statement_text(text: str) -> list[ParsedProFacilityStatement]:
    """Parse OCR text extracted from a PRO statement.

    The production upload path stores the raw PDF first. OCR integration can feed
    one page of recognized text at a time into this parser and persist the full
    structured payload for review.
    """
    pages = [page.strip() for page in re.split(r"\f+", text) if page.strip()]
    return [_parse_page(page) for page in pages]


def normalize_statement_name(value: str) -> str:
    cleaned = re.sub(r"\bCONNECTION HOMES(?: INC\.?)?\b", "", value.upper())
    cleaned = re.sub(r"[^A-Z0-9]+", " ", cleaned).strip()
    return re.sub(r"\s+", " ", cleaned)


def parse_money(value: str) -> Decimal:
    cleaned = value.replace("$", "").replace(",", "").replace(" ", "")
    if cleaned.startswith("."):
        cleaned = f"0{cleaned}"
    if cleaned.startswith("-."):
        cleaned = cleaned.replace("-.", "-0.", 1)
    return money(Decimal(cleaned))


def validate_statement_step(
    *,
    previous_balance: Decimal,
    interest: Decimal,
    draw: Decimal,
    reported_balance: Decimal,
) -> bool:
    expected = money(previous_balance + interest + draw)
    return abs(expected - reported_balance) <= Decimal("0.02")


def _parse_page(page: str) -> ParsedProFacilityStatement:
    lines = [line.strip() for line in page.splitlines() if line.strip()]
    property_name = _header_line(lines)
    borrowed_line = _line_containing(lines, "AMOUNT BORROWED")
    rate_line = _line_containing(lines, "ANNUAL INTEREST RATE")
    schedule_lines = [line for line in lines if _looks_like_schedule_row(line)]
    if not borrowed_line or not rate_line or not schedule_lines:
        raise ValueError(f"Could not parse PRO statement page for {property_name or 'unknown facility'}")

    advance_amount = _first_money(borrowed_line)
    advance_date = _first_date(borrowed_line)
    rate = Decimal(_first_percent(rate_line)) / Decimal("100")
    draws: list[ParsedProDraw] = []
    validation_errors: list[str] = []
    parsed_rows: list[_ParsedScheduleRow] = []
    previous_balance = advance_amount
    for line in schedule_lines:
        try:
            parsed_row = _parse_schedule_row(line)
        except ValueError as exc:
            validation_errors.append(str(exc))
            continue
        parsed_rows.append(parsed_row)
        if not validate_statement_step(
            previous_balance=previous_balance,
            interest=parsed_row.interest,
            draw=parsed_row.draw_amount or Decimal("0.00"),
            reported_balance=parsed_row.balance,
        ):
            expected = money(previous_balance + parsed_row.interest + (parsed_row.draw_amount or Decimal("0.00")))
            validation_errors.append(
                f"{parsed_row.txn_date.isoformat()}: expected balance {expected}, reported {parsed_row.balance}"
            )
        previous_balance = parsed_row.balance
        draw = _draw_from_row(line)
        if draw is not None:
            draws.append(draw)
    if not parsed_rows:
        raise ValueError(f"Could not parse schedule rows for {property_name or 'unknown facility'}")
    period_end_date = parsed_rows[-1].txn_date
    period_end_balance = parsed_rows[-1].balance

    return ParsedProFacilityStatement(
        property_name=property_name,
        original_advance_date=advance_date,
        original_advance_amount=advance_amount,
        annual_rate=rate,
        draws=draws,
        period_end_date=period_end_date,
        period_end_balance=period_end_balance,
        validation_errors=validation_errors,
    )


def _header_line(lines: list[str]) -> str:
    for index, line in enumerate(lines):
        if "AMOUNT BORROWED" in line.upper() and index > 0:
            return lines[index - 1]
    return lines[0] if lines else ""


def _line_containing(lines: list[str], needle: str) -> str:
    return next((line for line in lines if needle in line.upper()), "")


def _looks_like_schedule_row(line: str) -> bool:
    return not line.upper().startswith("TOTALS FOR") and bool(re.match(r"\d{1,2}/\d{1,2}/\d{2,4}\b", line)) and bool(MONEY_PATTERN.search(line))


def _first_money(line: str) -> Decimal:
    match = MONEY_PATTERN.search(line)
    if not match:
        raise ValueError(f"No money value found in line: {line}")
    return parse_money(match.group(0))


def _last_money(line: str) -> Decimal:
    matches = MONEY_PATTERN.findall(line)
    if not matches:
        raise ValueError(f"No money value found in line: {line}")
    return parse_money(matches[-1])


def _first_date(line: str) -> date:
    match = re.search(r"\b(\d{1,2})/(\d{1,2})/(\d{2,4})\b", line)
    if not match:
        raise ValueError(f"No date found in line: {line}")
    month, day, year = (int(part) for part in match.groups())
    year = 2000 + year if year < 100 else year
    return date(year, month, day)


def _first_percent(line: str) -> str:
    match = re.search(r"\b(\d+(?:\.\d+)?)\s*%", line)
    if not match:
        raise ValueError(f"No percentage found in line: {line}")
    return match.group(1)


@dataclass(frozen=True)
class _ParsedScheduleRow:
    txn_date: date
    interest: Decimal
    principal: Decimal
    balance: Decimal
    prepay: Decimal
    draw_amount: Decimal | None
    reference: str | None


def _parse_schedule_row(line: str) -> _ParsedScheduleRow:
    normalized = line.translate(
        str.maketrans(
            {
                "“": "-",
                "”": "-",
                "‘": "-",
                "’": "-",
                "−": "-",
                "–": "-",
                "—": "-",
            }
        )
    )
    normalized = re.sub(r"\s+", " ", normalized).strip()
    match = SCHEDULE_ROW_PATTERN.match(normalized)
    if not match:
        raise ValueError(f"Could not parse PRO schedule row: {line}")
    prepay = parse_money(match.group("prepay"))
    draw_amount = abs(prepay) if prepay < 0 else None
    return _ParsedScheduleRow(
        txn_date=_first_date(match.group("date")),
        interest=parse_money(match.group("interest")),
        principal=parse_money(match.group("principal")),
        balance=parse_money(match.group("balance")),
        prepay=prepay,
        draw_amount=draw_amount,
        reference=(match.group("reference") or "").strip() or None,
    )


def _draw_from_row(line: str) -> ParsedProDraw | None:
    row = _parse_schedule_row(line)
    if row.draw_amount is None:
        return None
    return ParsedProDraw(
        txn_date=row.txn_date,
        amount=row.draw_amount,
        reference=row.reference,
    )


def _trailing_reference(line: str) -> str | None:
    match = re.search(r"\b(?:PAP|Chq#|chq#|ch#).*$", line)
    return match.group(0).strip() if match else None
