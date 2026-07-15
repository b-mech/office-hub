from __future__ import annotations

from calendar import monthrange
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from decimal import ROUND_HALF_EVEN


CENT = Decimal("0.01")


@dataclass(frozen=True)
class ProFacility:
    facility_key: str
    property_name: str
    borrower: str
    annual_rate: Decimal
    original_advance_date: date
    original_advance_amount: Decimal


@dataclass(frozen=True)
class ProTransaction:
    txn_date: date
    txn_type: str
    amount: Decimal
    reference: str | None = None


@dataclass(frozen=True)
class LedgerEvent:
    event_date: date
    days: int
    interest: Decimal
    draw: Decimal
    repayment: Decimal
    balance: Decimal
    accrued_interest_running_total: Decimal
    reference: str | None = None
    event_type: str = "capitalization"


@dataclass(frozen=True)
class LedgerResult:
    events: list[LedgerEvent]
    balance_as_of: Decimal


def compute_ledger(
    facility: ProFacility,
    transactions: list[ProTransaction],
    as_of: date,
) -> LedgerResult:
    balance = money(facility.original_advance_amount)
    running_interest = Decimal("0.00")
    last_event_date = facility.original_advance_date
    events: list[LedgerEvent] = []
    txns_by_date = _txns_by_date(transactions)

    for event_date in _event_dates(facility.original_advance_date, transactions, as_of):
        days = (event_date - last_event_date).days
        interest = _interest_for_span(
            balance=balance,
            annual_rate=facility.annual_rate,
            period_anchor=facility.original_advance_date,
            start=last_event_date,
            end=event_date,
        )
        balance = money(balance + interest)
        running_interest = money(running_interest + interest)

        event_txns = txns_by_date.get(event_date, [])
        if event_txns:
            for txn in event_txns:
                draw = txn.amount if txn.txn_type == "draw" else Decimal("0.00")
                repayment = txn.amount if txn.txn_type == "repayment" else Decimal("0.00")
                balance = money(balance + draw - repayment)
                events.append(
                    LedgerEvent(
                        event_date=event_date,
                        days=days,
                        interest=interest,
                        draw=draw,
                        repayment=repayment,
                        balance=balance,
                        accrued_interest_running_total=running_interest,
                        reference=txn.reference,
                        event_type=txn.txn_type,
                    )
                )
                days = 0
                interest = Decimal("0.00")
        else:
            events.append(
                LedgerEvent(
                    event_date=event_date,
                    days=days,
                    interest=interest,
                    draw=Decimal("0.00"),
                    repayment=Decimal("0.00"),
                    balance=balance,
                    accrued_interest_running_total=running_interest,
                )
            )

        last_event_date = event_date

    return LedgerResult(events=events, balance_as_of=balance)


def balance_on(
    facility: ProFacility,
    transactions: list[ProTransaction],
    d: date,
) -> Decimal:
    ledger = compute_ledger(facility, transactions, d)
    if not ledger.events:
        last_date = facility.original_advance_date
        balance = money(facility.original_advance_amount)
    else:
        last_date = ledger.events[-1].event_date
        balance = ledger.events[-1].balance
    if d <= last_date:
        return ledger.balance_as_of
    interest = _interest_for_span(
        balance=balance,
        annual_rate=facility.annual_rate,
        period_anchor=facility.original_advance_date,
        start=last_date,
        end=d,
    )
    return money(balance + interest)


def money(value: Decimal | int | str) -> Decimal:
    # ProAuto statements use banker rounding on exact half-cent interest ties.
    return Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_EVEN)


def _event_dates(
    original_advance_date: date,
    transactions: list[ProTransaction],
    as_of: date,
) -> list[date]:
    dates = {
        txn.txn_date
        for txn in transactions
        if original_advance_date < txn.txn_date <= as_of
    }
    current = original_advance_date
    while True:
        current = _next_anniversary(original_advance_date, current)
        if current > as_of:
            break
        dates.add(current)
    return sorted(dates)


def _txns_by_date(transactions: list[ProTransaction]) -> dict[date, list[ProTransaction]]:
    grouped: dict[date, list[ProTransaction]] = {}
    for txn in sorted(transactions, key=lambda item: (item.txn_date, item.reference or "")):
        grouped.setdefault(txn.txn_date, []).append(txn)
    return grouped


def _interest_for_span(
    *,
    balance: Decimal,
    annual_rate: Decimal,
    period_anchor: date,
    start: date,
    end: date,
) -> Decimal:
    if end <= start:
        return Decimal("0.00")
    period_start, period_end = _period_bounds(period_anchor, end)
    period_days = Decimal((period_end - period_start).days)
    span_days = Decimal((end - start).days)
    return money(balance * annual_rate / Decimal("12") * span_days / period_days)


def _period_bounds(anchor: date, d: date) -> tuple[date, date]:
    current = anchor
    if d <= anchor:
        return anchor, _next_anniversary(anchor, anchor)
    while True:
        nxt = _next_anniversary(anchor, current)
        if d <= nxt:
            return current, nxt
        current = nxt


def _next_anniversary(anchor: date, current: date) -> date:
    month_index = current.year * 12 + current.month
    next_month = month_index + 1
    year = next_month // 12
    month = next_month % 12
    if month == 0:
        year -= 1
        month = 12
    day = min(anchor.day, monthrange(year, month)[1])
    return date(year, month, day)
