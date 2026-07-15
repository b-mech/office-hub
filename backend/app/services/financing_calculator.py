from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


STAGE_PCT: dict[str, Decimal] = {
    "FOUNDATION": Decimal("0.20"),
    "LOCKUP": Decimal("0.38"),
    "DRYWALL": Decimal("0.62"),
    "CABINETRY": Decimal("0.82"),
    "COMPLETED": Decimal("1.00"),
}


@dataclass(frozen=True)
class DrawCalculation:
    cumulative_entitled: Decimal | None
    draw_eligible: Decimal | None
    stage_is_estimate: bool
    flag: str | None
    formula: str


def calculate_draw(
    *,
    lender_type: str | None,
    stage: str | None,
    total_facility: Decimal | None,
    opening_balance: Decimal | None,
    already_drawn: Decimal | None,
) -> DrawCalculation:
    lender = (lender_type or "OTHER").upper()
    clean_stage = (stage or "NA").upper().strip() or "NA"
    drawn = already_drawn or Decimal("0")

    if clean_stage == "SYNC_CONFLICT":
        return DrawCalculation(None, None, False, "SYNC_CONFLICT", "Sheet has conflicting stage rows for this address.")

    if lender == "CLIENT":
        return DrawCalculation(None, None, False, "CHECK_OTP", "CLIENT terms vary by OTP.")

    if clean_stage in {"", "NA"}:
        return DrawCalculation(Decimal("0"), Decimal("0"), True, "NOT_STARTED", "No construction stage reached.")

    if lender == "PRO":
        if total_facility is None:
            return DrawCalculation(None, None, False, "FACILITY_NOT_SET", "PRO total facility is required.")
        entitled = _pro_entitled(clean_stage, total_facility)
        return _result(entitled, drawn, False, f"PRO {clean_stage}: {entitled} - {drawn}")

    if lender in {"SCU", "STRIDE", "RSU"}:
        if opening_balance is None:
            return DrawCalculation(None, None, True, "FACILITY_NOT_SET", f"{lender} opening balance is required.")
        pct = STAGE_PCT.get(clean_stage, Decimal("0"))
        entitled = (pct * opening_balance).quantize(Decimal("0.01"))
        calc = _result(entitled, drawn, True, f"{clean_stage} {pct:.0%} x {opening_balance} - {drawn}")
        if calc.flag is None and calc.draw_eligible == Decimal("0"):
            return calc
        if calc.flag is None:
            return DrawCalculation(calc.cumulative_entitled, calc.draw_eligible, True, "NO_PROGRESS_REPORT", calc.formula)
        return calc

    return DrawCalculation(None, None, False, "FACILITY_NOT_SET", "No lender calculation rule is configured.")


def _pro_entitled(stage: str, total_facility: Decimal) -> Decimal:
    if stage == "FOUNDATION":
        return Decimal("125000.00")
    if stage == "LOCKUP":
        return (total_facility * Decimal("0.55")).quantize(Decimal("0.01"))
    if stage == "DRYWALL":
        return (total_facility * Decimal("0.775")).quantize(Decimal("0.01"))
    if stage in {"CABINETRY", "COMPLETED"}:
        return total_facility
    return Decimal("0")


def _result(entitled: Decimal, drawn: Decimal, stage_is_estimate: bool, formula: str) -> DrawCalculation:
    if drawn > entitled:
        return DrawCalculation(entitled, Decimal("0"), stage_is_estimate, "OVER_DRAWN", formula)
    return DrawCalculation(entitled, max(Decimal("0"), entitled - drawn), stage_is_estimate, None, formula)
