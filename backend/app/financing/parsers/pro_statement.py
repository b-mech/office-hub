from __future__ import annotations

import re
from dataclasses import dataclass
from calendar import monthrange
from datetime import date
from datetime import timedelta
from decimal import Decimal

from app.financing.engines.pro import money


MONEY_PATTERN = re.compile(r"-?\$?\s*\.?[\d,]+\.\d{2}")
SCHEDULE_MONEY = r"-?\$?\s*(?:\.?[\d,]+\.\d{2}|\.?0{1,2})"
SCHEDULE_ROW_PATTERN = re.compile(
    r"^(?P<date>\S+)\s+"
    r"(?P<days>\S+)\s+"
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
    total_drawn: Decimal
    validation_errors: list[str]

    @property
    def reported_principal_drawn(self) -> Decimal:
        return money(self.original_advance_amount + self.total_drawn)

    @property
    def reported_accrued_interest(self) -> Decimal:
        return money(self.period_end_balance - self.reported_principal_drawn)


def parse_statement_text(text: str, *, period: str | None = None) -> list[ParsedProFacilityStatement]:
    """Parse OCR text extracted from a PRO statement.

    The production upload path stores the raw PDF first. OCR integration can feed
    one page of recognized text at a time into this parser and persist the full
    structured payload for review.
    """
    pages = [page.strip() for page in re.split(r"\f+", text) if page.strip()]
    return [_parse_page(page, period=period) for page in pages]


def normalize_statement_name(value: str) -> str:
    cleaned = re.sub(
        r"\b(?:CONNECTION HOMES(?: INC\.?)?|PRIVI HOLDINGS)\b",
        "",
        value.upper(),
    )
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


def _parse_page(page: str, *, period: str | None) -> ParsedProFacilityStatement:
    lines = [line.strip() for line in page.splitlines() if line.strip()]
    property_name = _header_line(lines)
    borrowed_line = _line_containing(lines, "AMOUNT BORROWED")
    rate_line = _line_containing(lines, "ANNUAL INTEREST RATE")
    schedule_lines = [line for line in lines if _looks_like_schedule_row(line)]
    if not borrowed_line or not rate_line or not schedule_lines:
        raise ValueError(f"Could not parse PRO statement page for {property_name or 'unknown facility'}")

    advance_amount, advance_date = _advance_details(page, borrowed_line)
    rate = _annual_rate(page, rate_line)
    draws: list[ParsedProDraw] = []
    validation_errors: list[str] = []
    parsed_rows: list[_ParsedScheduleRow] = []
    previous_balance = advance_amount
    previous_date = advance_date
    for line in schedule_lines:
        try:
            parsed_row = _parse_schedule_row(
                line,
                previous_date=previous_date,
                expected_day=advance_date.day,
            )
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
        previous_date = parsed_row.txn_date
        if parsed_row.draw_amount is not None:
            draws.append(
                ParsedProDraw(
                    txn_date=parsed_row.txn_date,
                    amount=parsed_row.draw_amount,
                    reference=parsed_row.reference,
                )
            )
    if not parsed_rows:
        raise ValueError(f"Could not parse schedule rows for {property_name or 'unknown facility'}")
    period_end_date = _period_end_date(period, advance_date.day, parsed_rows[-1].txn_date)
    period_end_balance = parsed_rows[-1].balance
    schedule_totals = _schedule_totals(lines)
    if schedule_totals is None:
        total_drawn = money(sum((draw.amount for draw in draws), Decimal("0.00")))
    else:
        total_drawn, accrued_interest = schedule_totals
        period_end_balance = money(advance_amount + total_drawn + accrued_interest)

    return ParsedProFacilityStatement(
        property_name=property_name,
        original_advance_date=advance_date,
        original_advance_amount=advance_amount,
        annual_rate=rate,
        draws=draws,
        period_end_date=period_end_date,
        period_end_balance=period_end_balance,
        total_drawn=total_drawn,
        validation_errors=validation_errors,
    )


def _header_line(lines: list[str]) -> str:
    for index, line in enumerate(lines):
        if "AMOUNT BORROWED" in line.upper() and index > 0:
            return lines[index - 1]
    return lines[0] if lines else ""


def _line_containing(lines: list[str], needle: str) -> str:
    return next((line for line in lines if needle in line.upper()), "")


def _advance_details(page: str, borrowed_line: str) -> tuple[Decimal, date]:
    source = borrowed_line
    if not MONEY_PATTERN.search(source) or not re.search(r"\d{1,2}/\d{1,2}/\d{2,4}", source):
        match = re.search(
            rf"(?P<amount>{MONEY_PATTERN.pattern})\s+advanced\s+on\s+"
            r"(?P<date>\d{1,2}/\d{1,2}/\d{2,4})",
            page,
            flags=re.IGNORECASE,
        )
        if not match:
            raise ValueError("Could not parse PRO original advance")
        source = f"{match.group('amount')} {match.group('date')}"
    return _first_money(source), _first_date(source)


def _annual_rate(page: str, rate_line: str) -> Decimal:
    source = rate_line
    if not re.search(r"\d+(?:\.\d+)?\s*%", source):
        match = re.search(r"(\d+(?:\.\d+)?)\s*%\s*\(Monthly compounding", page, flags=re.IGNORECASE)
        if not match:
            raise ValueError("Could not parse PRO annual interest rate")
        source = f"{match.group(1)}%"
    return Decimal(_first_percent(source)) / Decimal("100")


def _looks_like_schedule_row(line: str) -> bool:
    first_token = line.split(maxsplit=1)[0] if line.split() else ""
    return (
        not line.upper().startswith("TOTALS FOR")
        and first_token.count("/") >= 2
        and bool(re.search(r"20\d{2}", first_token))
        and bool(MONEY_PATTERN.search(line))
    )


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


def _parse_schedule_row(
    line: str,
    *,
    previous_date: date | None = None,
    expected_day: int | None = None,
) -> _ParsedScheduleRow:
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
                "«": "-",
                "»": "-",
                "~": "-",
                "+": "-",
                "§": "5",
            }
        )
    )
    normalized = re.sub(r"(?<=\d)H(?=\d)", "/", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"^T/", "7/", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"(?<=/)H(?=\d)", "", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"(?<=[.\-\s])[OGC](?=\d|\s)", "0", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"(?<=\d)[OGC](?=\d)", "0", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    match = SCHEDULE_ROW_PATTERN.match(normalized)
    if not match:
        raise ValueError(f"Could not parse PRO schedule row: {line}")
    prepay = parse_money(match.group("prepay"))
    draw_amount = _normalize_large_statement_amount(abs(prepay)) if prepay < 0 else None
    txn_date = _schedule_date(
        match.group("date"),
        days_token=match.group("days"),
        previous_date=previous_date,
        expected_day=expected_day,
    )
    return _ParsedScheduleRow(
        txn_date=txn_date,
        interest=parse_money(match.group("interest")),
        principal=parse_money(match.group("principal")),
        balance=parse_money(match.group("balance")),
        prepay=prepay,
        draw_amount=draw_amount,
        reference=(match.group("reference") or "").strip() or None,
    )


def _schedule_date(
    value: str,
    *,
    days_token: str,
    previous_date: date | None,
    expected_day: int | None,
) -> date:
    cleaned = value.upper()
    cleaned = re.sub(r"^T/", "7/", cleaned)
    cleaned = re.sub(r"(?<=\d)H(?=\d)", "/", cleaned)
    cleaned = re.sub(r"(?<=/)H(?=\d)", "", cleaned)
    cleaned = cleaned.translate(str.maketrans({"O": "0", "G": "0", "C": "0", "I": "1", "L": "1"}))
    parts = cleaned.split("/")
    if len(parts) == 3 and all(part.isdigit() for part in parts):
        month, day, year = (int(part) for part in parts)
        year = 2000 + year if year < 100 else year
        if 2000 <= year <= 2100 and 1 <= month <= 12:
            if day > monthrange(year, month)[1] and day % 10 == 6:
                day -= 6
            try:
                return date(year, month, day)
            except ValueError:
                pass

    digits = re.sub(r"\D", "", days_token)
    if previous_date is not None and digits:
        elapsed = int(digits)
        if 0 < elapsed <= 62:
            return previous_date + timedelta(days=elapsed)

    if len(parts) == 3 and parts[0].isdigit() and parts[2].isdigit() and expected_day:
        month = int(parts[0])
        year = int(parts[2])
        year = 2000 + year if year < 100 else year
        if 2000 <= year <= 2100 and 1 <= month <= 12:
            return date(year, month, min(expected_day, monthrange(year, month)[1]))
    raise ValueError(f"Could not parse PRO schedule date: {value}")


def _period_end_date(period: str | None, expected_day: int, parsed_date: date) -> date:
    if not period or not re.fullmatch(r"\d{4}-\d{2}", period):
        return parsed_date
    year, month = (int(part) for part in period.split("-"))
    if (parsed_date.year, parsed_date.month) == (year, month):
        return parsed_date
    return date(year, month, min(expected_day, monthrange(year, month)[1]))


def _schedule_totals(lines: list[str]) -> tuple[Decimal, Decimal] | None:
    totals_line = next((line for line in reversed(lines) if line.upper().startswith("TOTALS FOR SCHEDU")), None)
    if totals_line is None:
        return None
    totals_pattern = re.compile(r"(?<![\d.])-?\$?\s*(?:[\d,]+\.\d{2}|\.0{1,2}|0{1,2})(?![\d.])")
    values = [parse_money(value) for value in totals_pattern.findall(totals_line)]
    if len(values) < 2:
        return None
    total_drawn = _normalize_large_statement_amount(abs(values[-1]))
    principal_and_interest = abs(values[-2])
    accrued_interest = money(max(Decimal("0.00"), principal_and_interest - total_drawn))
    return total_drawn, accrued_interest


def _normalize_large_statement_amount(value: Decimal) -> Decimal:
    rounded = (value / Decimal("100")).quantize(Decimal("1")) * Decimal("100")
    if value >= Decimal("1000") and abs(value - rounded) <= Decimal("1"):
        return money(rounded)
    return money(value)


def _trailing_reference(line: str) -> str | None:
    match = re.search(r"\b(?:PAP|Chq#|chq#|ch#).*$", line)
    return match.group(0).strip() if match else None
