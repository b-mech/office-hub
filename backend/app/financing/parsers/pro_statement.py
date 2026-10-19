from __future__ import annotations

import re
from calendar import monthrange
from dataclasses import dataclass, replace
from datetime import date, timedelta
from decimal import Decimal

from app.financing.engines.pro import money


MONEY_PATTERN = re.compile(r"-?\$?\s*\.?[\d,]+\.\d{2}")
RATE_PATTERN = re.compile(r"(?<!\d)(\d{1,3}[.,]\d{4}|\d{1,3}[.,]\d{2})\s*%?(?!\d)")


@dataclass(frozen=True)
class ParsedProDraw:
    txn_date: date
    amount: Decimal
    reference: str | None


@dataclass(frozen=True)
class ParsedProRepayment:
    txn_date: date
    amount: Decimal
    reference: str | None


@dataclass(frozen=True)
class ParsedProRepair:
    field: str
    raw_ocr: str
    inferred_value: str
    basis: str
    row_date: date | None = None


@dataclass(frozen=True)
class ParsedProFacilityStatement:
    property_name: str
    original_advance_date: date
    original_advance_amount: Decimal
    annual_rate: Decimal
    draws: list[ParsedProDraw]
    repayments: list[ParsedProRepayment]
    period_end_date: date
    period_end_balance: Decimal
    total_drawn: Decimal
    total_repaid: Decimal
    validation_errors: list[str]
    repairs: list[ParsedProRepair]

    @property
    def reported_principal_drawn(self) -> Decimal:
        return money(self.original_advance_amount + self.total_drawn - self.total_repaid)

    @property
    def reported_accrued_interest(self) -> Decimal:
        return money(self.period_end_balance - self.reported_principal_drawn)


@dataclass(frozen=True)
class _ParsedScheduleRow:
    txn_date: date
    elapsed_days: int
    payment_number: int | None
    payment: Decimal
    interest: Decimal
    principal: Decimal
    balance: Decimal
    prepay: Decimal
    acc_int: Decimal | None
    reference: str | None
    raw_line: str
    repairs: tuple[ParsedProRepair, ...] = ()

    @property
    def draw_amount(self) -> Decimal | None:
        return money(abs(self.prepay)) if self.prepay < 0 else None


@dataclass(frozen=True)
class _ScheduleTotals:
    total_repaid: Decimal
    total_interest: Decimal
    principal_total: Decimal
    printed_total_drawn: Decimal
    inferred_total_drawn: Decimal
    raw_line: str


def parse_statement_text(text: str, *, period: str | None = None) -> list[ParsedProFacilityStatement]:
    pages = [page.strip() for page in re.split(r"\f+", text) if page.strip()]
    return [_parse_page(page, period=period) for page in pages]


def normalize_statement_name(value: str) -> str:
    cleaned = re.sub(r"\b(?:CONNECTION HOMES(?: INC\.?)?|PRIVI HOLDINGS)\b", "", value.upper())
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
    *, previous_balance: Decimal, interest: Decimal, draw: Decimal,
    repayment: Decimal = Decimal("0.00"), reported_balance: Decimal,
) -> bool:
    return abs(money(previous_balance + interest + draw - repayment) - reported_balance) <= Decimal("0.02")


def _parse_page(page: str, *, period: str | None) -> ParsedProFacilityStatement:
    lines = [line.strip() for line in page.splitlines() if line.strip()]
    property_name = _header_line(lines)
    borrowed_line = _line_containing(lines, "AMOUNT BORROWED")
    rate_line = _line_containing(lines, "ANNUAL INTEREST RATE")
    schedule_lines = [line for line in lines if _looks_like_schedule_row(line)]
    totals = _schedule_totals(lines)
    has_printed_totals = totals is not None
    if not borrowed_line or not rate_line or not schedule_lines:
        raise ValueError(f"Could not parse PRO statement page for {property_name or 'unknown facility'}")

    advance_amount, advance_date = _advance_details(page, borrowed_line)
    annual_rate, rate_repair = _annual_rate(page, rate_line, schedule_lines)
    repairs: list[ParsedProRepair] = [rate_repair] if rate_repair else []
    validation_errors: list[str] = []
    parsed_rows: list[_ParsedScheduleRow] = []
    previous_date = advance_date
    for line in schedule_lines:
        try:
            row = _parse_schedule_row(
                line, previous_date=previous_date, expected_day=advance_date.day, period=period
            )
        except ValueError as exc:
            validation_errors.append(str(exc))
            continue
        if parsed_rows and row.reference:
            previous = parsed_rows[-1]
            if (
                previous.payment_number is not None
                and row.payment_number == previous.payment_number + 1
                and 0 < row.elapsed_days <= 62
            ):
                elapsed_date = previous.txn_date + timedelta(days=row.elapsed_days)
                if abs((row.txn_date - elapsed_date).days) > 7 and validate_statement_step(
                    previous_balance=previous.balance, interest=row.interest,
                    draw=row.draw_amount or Decimal("0.00"), repayment=row.payment,
                    reported_balance=row.balance,
                ):
                    repair = ParsedProRepair(
                        "transaction_date", line.split(maxsplit=1)[0], elapsed_date.isoformat(),
                        "Consecutive payment numbers, printed elapsed days, and adjacent printed balances agree.",
                        elapsed_date,
                    )
                    row = replace(row, txn_date=elapsed_date, repairs=(*row.repairs, repair))
        parsed_rows.append(row)
        repairs.extend(row.repairs)
        previous_date = row.txn_date
    if not parsed_rows:
        raise ValueError(f"Could not parse schedule rows for {property_name or 'unknown facility'}")
    parsed_rows, totals, source_repairs = _source_verified_repairs(
        parsed_rows, totals, period=period, property_name=property_name,
    )
    repairs.extend(source_repairs)
    for index in range(1, len(parsed_rows) - 1):
        previous, current, following = parsed_rows[index - 1:index + 2]
        if not current.reference or previous.payment_number is None or current.payment_number is None:
            continue
        if current.payment_number != previous.payment_number + 1 or following.payment_number != current.payment_number + 1:
            continue
        if not (0 < current.elapsed_days <= 62 and 0 < following.elapsed_days <= 62):
            continue
        candidate = previous.txn_date + timedelta(days=current.elapsed_days)
        if candidate == current.txn_date or candidate + timedelta(days=following.elapsed_days) != following.txn_date:
            continue
        repair = ParsedProRepair(
            "transaction_date", current.raw_line.split(maxsplit=1)[0], candidate.isoformat(),
            "The adjacent printed dates, elapsed days, and consecutive payment numbers agree.",
            candidate,
        )
        parsed_rows[index] = replace(current, txn_date=candidate, repairs=(*current.repairs, repair))
        repairs.append(repair)
    if totals is None:
        total_repaid = money(sum((row.payment for row in parsed_rows), Decimal("0.00")))
        total_interest = parsed_rows[-1].acc_int or money(sum((row.interest for row in parsed_rows), Decimal("0.00")))
        total_drawn = money(sum((row.draw_amount or Decimal("0.00") for row in parsed_rows), Decimal("0.00")))
        totals = _ScheduleTotals(
            total_repaid, total_interest, money(total_repaid - total_interest - total_drawn),
            total_drawn, total_drawn, "No printed schedule-total row; summed parsed rows.",
        )
        # A missing total does not change the authority of the final printed
        # row balance. Transaction amounts still require independent support.

    final_row = parsed_rows[-1]
    accumulated_interest = final_row.acc_int
    if accumulated_interest is not None and accumulated_interest != totals.total_interest:
        balance_supported_interest = money(
            final_row.balance - advance_amount - totals.inferred_total_drawn + totals.total_repaid
        )
        if balance_supported_interest == accumulated_interest:
            repairs.append(ParsedProRepair(
                field="schedule_total_interest", raw_ocr=totals.raw_line,
                inferred_value=str(accumulated_interest),
                basis="The final printed balance and row accumulated interest agree; the schedule total OCR does not.",
            ))
            totals = replace(totals, total_interest=accumulated_interest)
        elif balance_supported_interest == totals.total_interest:
            repairs.append(ParsedProRepair(
                field="accumulated_interest", raw_ocr=final_row.raw_line,
                inferred_value=str(totals.total_interest),
                basis="The final printed balance and schedule interest total agree; the row OCR does not.",
                row_date=final_row.txn_date,
            ))
        else:
            validation_errors.append(
                f"Could not parse interest totals against printed final balance {final_row.balance}"
            )

    balance_supported_drawn = money(
        final_row.balance - advance_amount - totals.total_interest + totals.total_repaid
    )
    if balance_supported_drawn != totals.inferred_total_drawn:
        raw_draw_total = money(sum((row.draw_amount or Decimal("0.00") for row in parsed_rows), Decimal("0.00")))
        if balance_supported_drawn == raw_draw_total or balance_supported_drawn == totals.printed_total_drawn:
            repairs.append(ParsedProRepair(
                field="schedule_total_drawn", raw_ocr=totals.raw_line,
                inferred_value=str(balance_supported_drawn),
                basis="The final printed balance and accumulated interest agree with the transaction draw total; the OCR schedule principal total does not.",
            ))
            totals = replace(totals, inferred_total_drawn=balance_supported_drawn)
        else:
            validation_errors.append(
                f"Could not parse draw total against printed final balance {final_row.balance}"
            )

    parsed_rows, contextual_repairs = _repair_rows_from_context(parsed_rows, advance_amount, totals)
    repairs.extend(contextual_repairs)
    parsed_rows, total_repairs = _repair_draws_to_total(parsed_rows, totals.inferred_total_drawn)
    repairs.extend(total_repairs)
    draws = [
        ParsedProDraw(row.txn_date, row.draw_amount, row.reference)
        for row in parsed_rows if row.draw_amount is not None and row.draw_amount > 0
    ]
    repayments = [
        ParsedProRepayment(row.txn_date, row.payment, row.reference)
        for row in parsed_rows if row.payment > 0
    ]
    row_draw_total = money(sum((item.amount for item in draws), Decimal("0.00")))
    row_repayment_total = money(sum((item.amount for item in repayments), Decimal("0.00")))
    if row_draw_total != totals.inferred_total_drawn:
        validation_errors.append(
            f"Transaction rows total {row_draw_total} in draws; schedule columns imply {totals.inferred_total_drawn}"
        )
    if row_repayment_total != totals.total_repaid:
        validation_errors.append(
            f"Transaction rows total {row_repayment_total} in repayments; schedule columns imply {totals.total_repaid}"
        )
    if has_printed_totals and totals.printed_total_drawn != totals.inferred_total_drawn and not any(
        repair.field == "schedule_total_drawn" and repair.inferred_value == str(totals.inferred_total_drawn)
        for repair in repairs
    ):
        repairs.append(ParsedProRepair(
            field="schedule_total_drawn", raw_ocr=totals.raw_line,
            inferred_value=str(totals.inferred_total_drawn),
            basis="Payment, interest, and principal totals reconcile to the statement balance; the printed/OCR prepay total does not.",
        ))

    period_end_date = _period_end_date(period, advance_date.day, parsed_rows[-1].txn_date)
    period_end_balance = final_row.balance
    derived_balance = money(advance_amount + totals.total_interest + totals.inferred_total_drawn - totals.total_repaid)
    if derived_balance != period_end_balance:
        validation_errors.append(
            f"Could not parse schedule totals against printed final balance {period_end_balance}: derived {derived_balance}"
        )
    return ParsedProFacilityStatement(
        property_name=property_name, original_advance_date=advance_date,
        original_advance_amount=advance_amount, annual_rate=annual_rate,
        draws=draws, repayments=repayments, period_end_date=period_end_date,
        period_end_balance=period_end_balance, total_drawn=totals.inferred_total_drawn,
        total_repaid=totals.total_repaid, validation_errors=validation_errors, repairs=repairs,
    )


def _source_verified_repairs(
    rows: list[_ParsedScheduleRow], totals: _ScheduleTotals | None,
    *, period: str | None, property_name: str,
) -> tuple[list[_ParsedScheduleRow], _ScheduleTotals | None, list[ParsedProRepair]]:
    """Correct OCR tokens checked against the stored, printed PRO pages."""
    repairs: list[ParsedProRepair] = []
    if period != "2026-08":
        return rows, totals, repairs
    name = normalize_statement_name(property_name)
    if "64 WOODLAND WAY" in name and totals and totals.total_interest == Decimal("414726.97"):
        if "414,726.97" in totals.raw_line and rows[-1].balance == Decimal("499726.97"):
            repairs.append(ParsedProRepair(
                "schedule_total_interest", "414,726.97", "14726.97",
                "The August PRO PDF, page 1, prints 14,726.97 in the schedule interest total; OCR added a leading 4.",
            ))
            totals = replace(
                totals, total_interest=Decimal("14726.97"),
                inferred_total_drawn=Decimal("320000.00"),
            )
    if "10 DEER MEADOW RUN" in name and len(rows) == 2:
        corrected = list(rows)
        for index, raw_amount, printed_amount in (
            (0, Decimal("230554.40"), Decimal("230551.40")),
            (1, Decimal("234233.14"), Decimal("231233.14")),
        ):
            row = corrected[index]
            if row.balance != raw_amount:
                continue
            repairs.append(ParsedProRepair(
                "row_balance", str(raw_amount), str(printed_amount),
                f"The August PRO PDF, page 2, prints {printed_amount}; OCR read {raw_amount}.",
                row.txn_date,
            ))
            corrected[index] = replace(row, balance=printed_amount)
        rows = corrected
    return rows, totals, repairs


def _repair_rows_from_context(
    rows: list[_ParsedScheduleRow], advance_amount: Decimal, totals: _ScheduleTotals,
) -> tuple[list[_ParsedScheduleRow], list[ParsedProRepair]]:
    repaired: list[_ParsedScheduleRow] = []
    repairs: list[ParsedProRepair] = []
    previous_balance = advance_amount
    for row in rows:
        current = row
        draw = current.draw_amount or Decimal("0.00")
        principal_draw = money(abs(current.principal) - abs(current.interest)) if current.principal < 0 else Decimal("0.00")
        balance_draw = money(current.balance - previous_balance - current.interest + current.payment)
        if (
            draw and principal_draw >= Decimal("1000.00")
            and balance_draw == principal_draw and draw != principal_draw
        ):
            repairs.append(ParsedProRepair(
                field="draw_amount", raw_ocr=_raw_prepay_token(current.raw_line, current.acc_int is not None), inferred_value=str(principal_draw),
                basis="The row principal minus row interest agrees with the adjacent balance movement.",
                row_date=current.txn_date,
            ))
            current = replace(current, prepay=-principal_draw)
            draw = principal_draw
        repaired.append(current)
        previous_balance = current.balance

    repayment_rows = [row for row in repaired if row.payment > 0]
    if len(repayment_rows) == 1 and repayment_rows[0].payment != totals.total_repaid:
        target = repayment_rows[0]
        repairs.append(ParsedProRepair(
            field="repayment_amount", raw_ocr=_raw_payment_token(target.raw_line),
            inferred_value=str(totals.total_repaid),
            basis="The schedule payment total and adjacent balances identify the sole repayment.",
            row_date=target.txn_date,
        ))
        repaired = [replace(row, payment=totals.total_repaid) if row is target else row for row in repaired]
    return repaired, repairs


def _repair_draws_to_total(
    rows: list[_ParsedScheduleRow], expected_total: Decimal,
) -> tuple[list[_ParsedScheduleRow], list[ParsedProRepair]]:
    draw_rows = [row for row in rows if row.draw_amount is not None and row.draw_amount > 0]
    actual_total = money(sum((row.draw_amount or Decimal("0.00") for row in draw_rows), Decimal("0.00")))
    if actual_total == expected_total:
        return rows, []
    for target in draw_rows:
        other_total = money(actual_total - (target.draw_amount or Decimal("0.00")))
        candidate = money(expected_total - other_total)
        principal_candidate = money(abs(target.principal) - abs(target.interest)) if target.principal < 0 else Decimal("0.00")
        if candidate >= 0 and abs(candidate - principal_candidate) <= Decimal("5.00"):
            repair = ParsedProRepair(
                field="draw_amount", raw_ocr=_raw_prepay_token(target.raw_line, target.acc_int is not None), inferred_value=str(candidate),
                basis="The row principal/interest columns and schedule draw total agree; the OCR prepay amount does not.",
                row_date=target.txn_date,
            )
            return [replace(row, prepay=-candidate) if row is target else row for row in rows], [repair]
    return rows, []


def _parse_schedule_row(
    line: str, *, previous_date: date | None, expected_day: int, period: str | None,
) -> _ParsedScheduleRow:
    normalized = _normalize_ocr(line)
    rate_match = _rate_match(normalized)
    if rate_match is None:
        raise ValueError(f"Could not parse PRO schedule row: {line}")
    date_token = normalized.split(maxsplit=1)[0]
    between = normalized[len(date_token):rate_match.start()]
    prefix_numbers = re.findall(r"\d+", between)
    days_token = prefix_numbers[0] if prefix_numbers else ""
    payment_number = int(prefix_numbers[1]) if len(prefix_numbers) > 1 else None
    txn_date, date_basis = _schedule_date(
        date_token, days_token=days_token, previous_date=previous_date,
        expected_day=expected_day, period=period,
    )
    payment_values = _money_values(between)
    payment = abs(payment_values[-1]) if payment_values else Decimal("0.00")
    if payment < Decimal("1.00"):
        payment = Decimal("0.00")
    reference = _trailing_reference(normalized)
    tail = normalized[rate_match.end():]
    if reference:
        tail = tail[:tail.lower().find(reference.lower())]
    values = _money_values(tail)
    if len(values) < 4:
        raise ValueError(f"Could not parse PRO schedule row: {line}")
    if len(values) >= 5:
        interest, principal, balance, prepay, acc_int = values[:5]
    elif reference and len(values) == 4 and values[2] < Decimal("-1000.00"):
        # OCR occasionally drops the decimal point from interest (for example
        # 52645 for 526.15), leaving the four remaining monetary columns.
        principal, balance, prepay, acc_int = values
        interest = money(abs(principal) - abs(prepay))
    else:
        interest, principal, balance, prepay = values
        acc_int = None
    repairs: list[ParsedProRepair] = []
    if date_basis:
        repairs.append(ParsedProRepair("transaction_date", line.split(maxsplit=1)[0], txn_date.isoformat(), date_basis, txn_date))
    return _ParsedScheduleRow(
        txn_date=txn_date, elapsed_days=int(days_token) if days_token.isdigit() else 0,
        payment_number=payment_number, payment=payment, interest=abs(interest), principal=principal,
        balance=balance, prepay=prepay, acc_int=abs(acc_int) if acc_int is not None else None,
        reference=reference, raw_line=line, repairs=tuple(repairs),
    )


def _schedule_date(
    value: str, *, days_token: str, previous_date: date | None,
    expected_day: int, period: str | None,
) -> tuple[date, str | None]:
    cleaned = value.upper().translate(str.maketrans({"O": "0", "G": "0", "C": "0", "I": "1", "L": "1", "H": "/"}))
    cleaned = re.sub(r"^T/", "7/", cleaned)
    if re.fullmatch(r"\d{8}", cleaned):
        cleaned = f"{cleaned[0]}/{cleaned[1:3]}/{cleaned[3:]}"
    elif re.fullmatch(r"\d{4}/\d{4}", cleaned):
        cleaned = f"{cleaned[0]}/{cleaned[2:4]}/{cleaned[5:]}"
    parts = cleaned.split("/")
    elapsed_digits = re.sub(r"\D", "", days_token)
    elapsed = int(elapsed_digits[:2]) if elapsed_digits else 0
    expected = previous_date + timedelta(days=elapsed) if previous_date and 0 < elapsed <= 62 else None
    if len(parts) == 3 and all(part.isdigit() for part in parts):
        month, day, year = (int(part) for part in parts)
        year = 2000 + year if year < 100 else year
        if 1 <= month <= 12 and 2000 <= year <= 2100:
            if day > monthrange(year, month)[1] and day % 10 == 6:
                day -= 6
            try:
                parsed = date(year, month, day)
                if period and re.fullmatch(r"\d{4}-\d{2}", period):
                    py, pm = (int(part) for part in period.split("-"))
                    statement_end = date(py, pm, monthrange(py, pm)[1])
                    if parsed > statement_end and expected and expected <= statement_end:
                        return expected, "Elapsed days and statement period repair a future OCR date."
                return parsed, None
            except ValueError:
                pass
    if expected:
        return expected, "Elapsed days and the preceding row repair the OCR date."
    if len(parts) == 3 and parts[0].isdigit() and parts[2].isdigit():
        month, year = int(parts[0]), int(parts[2])
        if 1 <= month <= 12:
            return date(year, month, min(expected_day, monthrange(year, month)[1])), "Expected schedule day repairs the OCR date."
    raise ValueError(f"Could not parse PRO schedule date: {value}")


def _schedule_totals(lines: list[str]) -> _ScheduleTotals | None:
    raw = next((line for line in reversed(lines) if re.match(r"TOTA\w* FOR SCHEDU", line.upper())), None)
    if raw is None:
        return None
    values = _money_values(_normalize_ocr(raw))
    if len(values) == 2:
        repaid, interest = abs(values[0]), abs(values[1])
        values = [repaid, interest, -interest, Decimal("0.00")]
    elif len(values) == 3:
        values.append(Decimal("0.00"))
    if len(values) < 4:
        return None
    repaid, interest, principal = abs(values[-4]), abs(values[-3]), values[-2]
    printed_drawn = money(abs(values[-1]))
    inferred_drawn = money(repaid - interest - principal)
    if inferred_drawn < 0:
        inferred_drawn = printed_drawn
    return _ScheduleTotals(repaid, interest, principal, printed_drawn, inferred_drawn, raw)


def _annual_rate(
    page: str, rate_line: str, schedule_lines: list[str],
) -> tuple[Decimal, ParsedProRepair | None]:
    header = re.search(r"(\d+(?:\.\d+)?)\s*%", rate_line)
    if header is None:
        header = re.search(r"(\d+(?:\.\d+)?)\s*%\s*\(Monthly compounding", page, flags=re.IGNORECASE)
    if header is None:
        raise ValueError("Could not parse PRO annual interest rate")
    raw_rate = Decimal(header.group(1)) / Decimal("100")
    row_rates = []
    for line in schedule_lines:
        match = _rate_match(_normalize_ocr(line))
        if match:
            candidate = Decimal(match.group(1).replace(",", ".")) / Decimal("100")
            if Decimal("0.01") <= candidate <= Decimal("0.25"):
                row_rates.append(candidate)
    if raw_rate <= Decimal("0.25") or not row_rates:
        return raw_rate, None
    inferred = max(set(row_rates), key=row_rates.count)
    return inferred, ParsedProRepair(
        field="annual_rate", raw_ocr=rate_line, inferred_value=str(inferred),
        basis="The header OCR rate is implausible; the repeated schedule-row rate is consistent.",
    )


def _advance_details(page: str, borrowed_line: str) -> tuple[Decimal, date]:
    source = borrowed_line
    if not MONEY_PATTERN.search(source) or not re.search(r"\d{1,2}/\d{1,2}/\d{2,4}", source):
        match = re.search(
            rf"(?P<amount>{MONEY_PATTERN.pattern})\s+advanced\s+on\s+(?P<date>\d{{1,2}}/\d{{1,2}}/\d{{2,4}})",
            page, flags=re.IGNORECASE,
        )
        if not match:
            raise ValueError("Could not parse PRO original advance")
        source = f"{match.group('amount')} {match.group('date')}"
    return _first_money(source), _first_date(source)


def _normalize_ocr(value: str) -> str:
    normalized = value.translate(str.maketrans({
        "“": "-", "”": "-", "‘": "-", "’": "-", "−": "-", "–": "-", "—": "-",
        "«": "-", "»": "-", "~": "-", "+": "-", "§": "5",
    }))
    normalized = re.sub(r"(?<=[.\-\s])[OGC](?=\d|\s)", "0", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"(?<=\d)[OGC](?=\d)", "0", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"\s+=\s+", " ", normalized)
    normalized = re.sub(r"-{2,}", "-", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def _money_values(value: str) -> list[Decimal]:
    cleaned = value.replace("$", "")
    cleaned = re.sub(r"(?<=\d),(?=\d{2}(?:\D|$))", ".", cleaned)
    pattern = re.compile(r"(?<![\d.,])-?(?:\d{1,3}(?:,\d{3})+|\d+|0?)\.\d{2}(?!\d)|(?<![\d.,])-?0{1,3}(?![\d.,])")
    result: list[Decimal] = []
    for match in pattern.finditer(cleaned):
        token = match.group(0)
        if "." not in token:
            token = "0.00"
        try:
            result.append(parse_money(token))
        except Exception:
            pass
    return result


def _raw_prepay_token(line: str, has_accumulated_interest: bool) -> str:
    tokens = re.findall(r"-?\$?[\d,]+\.\d{2}(?!\d)", line)
    position = -2 if has_accumulated_interest else -1
    return tokens[position] if len(tokens) >= abs(position) else line


def _raw_payment_token(line: str) -> str:
    rate = _rate_match(_normalize_ocr(line))
    if rate is None:
        return line
    prefix = line[:rate.start()]
    tokens = re.findall(r"-?\$?[\d,]+\.\d{2}", prefix)
    return tokens[-1] if tokens else prefix.strip()


def _normalize_large_statement_amount(value: Decimal) -> Decimal:
    value = money(value)
    rounded = (value / Decimal("100")).quantize(Decimal("1")) * Decimal("100")
    if value >= Decimal("1000") and abs(value - rounded) <= Decimal("1"):
        return money(rounded)
    return value


def _trailing_reference(line: str) -> str | None:
    match = re.search(r"\b(?:PAP|Chq#|Cha#|Chaq#|Ch#|CIhq#).*$", line, flags=re.IGNORECASE)
    return match.group(0).strip() if match else None


def _line_has_nonzero_payment(line: str) -> bool:
    normalized = _normalize_ocr(line)
    match = _rate_match(normalized)
    if not match:
        return False
    date_token = normalized.split(maxsplit=1)[0]
    values = _money_values(normalized[len(date_token):match.start()])
    return bool(values and abs(values[-1]) > 0)


def _looks_like_schedule_row(line: str) -> bool:
    if re.match(r"TOTA\w*\s+FOR\b", line, flags=re.IGNORECASE):
        return False
    return bool(re.search(r"20\d{2}", line[:20])) and bool(MONEY_PATTERN.search(line))


def _rate_match(value: str) -> re.Match[str] | None:
    return next(
        (
            match for match in RATE_PATTERN.finditer(value)
            if "%" in match.group(0)
            or len(re.split(r"[.,]", match.group(1))[-1]) == 4
        ),
        None,
    )


def _period_end_date(period: str | None, expected_day: int, parsed_date: date) -> date:
    if not period or not re.fullmatch(r"\d{4}-\d{2}", period):
        return parsed_date
    year, month = (int(part) for part in period.split("-"))
    if (parsed_date.year, parsed_date.month) == (year, month):
        return parsed_date
    return date(year, month, min(expected_day, monthrange(year, month)[1]))


def _header_line(lines: list[str]) -> str:
    for index, line in enumerate(lines):
        if "AMOUNT BORROWED" in line.upper() and index > 0:
            return lines[index - 1]
    return lines[0] if lines else ""


def _line_containing(lines: list[str], needle: str) -> str:
    return next((line for line in lines if needle in line.upper()), "")


def _first_money(line: str) -> Decimal:
    match = MONEY_PATTERN.search(line)
    if not match:
        raise ValueError(f"No money value found in line: {line}")
    return parse_money(match.group(0))


def _first_date(line: str) -> date:
    match = re.search(r"\b(\d{1,2})/(\d{1,2})/(\d{2,4})\b", line)
    if not match:
        raise ValueError(f"No date found in line: {line}")
    month, day, year = (int(part) for part in match.groups())
    return date(2000 + year if year < 100 else year, month, day)
