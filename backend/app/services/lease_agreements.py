"""Form 1 context construction and validation. Legal text lives only in the approved DOCX."""
from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from app.models.rentals import RentalProperty

TENANT_SERVICES = "Gas, hydro, water and sewer, internet, TV, snow removal, lawn care including cutting grass."
LANDLORD_WATER_SERVICES = (
    "Gas, hydro, internet, TV, snow removal, lawn care including cutting grass, water and sewer. "
    "Water and sewer are billed to the tenant at the actual amount shown on the municipal utility bill "
    "for the rental unit; the landlord will give the tenant a copy of each bill, and the amount is payable "
    "with the next month's rent."
)
LANDLORD_SERVICES = "None. The tenant is responsible for all services and utilities listed in 5(a)."
EMAIL = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
OPTIONAL = (
    "fixed_start", "fixed_end", "periodic_start", "periodic_period", "security_deposit_amount",
    "security_deposit_date", "pet_deposit_amount", "pet_deposit_date", "parking_spaces",
    "parking_amount", "other_charge_desc", "other_charge_amount", "rent_discount",
    "guideline_increase_date", "above_guideline_date", "above_guideline_rent",
    "discount_conditions", "discount_change", "discount_increase_amount", "discount_reduced_amount",
    "agi_max_amount", "services_landlord_pays", "utility_exceptions", "occupants", "other_attachments",
)


def money(value: Any, *, optional: bool = False) -> str | None:
    if value is None or str(value).strip() == "":
        if optional:
            return None
        raise ValueError("A money amount is required")
    try:
        amount = Decimal(str(value).replace(",", "").replace("$", ""))
    except InvalidOperation as exc:
        raise ValueError("Enter a valid money amount") from exc
    if not amount.is_finite() or amount < 0 or amount.as_tuple().exponent < -2:
        raise ValueError("Money must be nonnegative with at most two decimal places")
    return f"{amount:,.2f}"


def long_date(value: Any) -> str | None:
    if value is None or str(value).strip() == "":
        return None
    if isinstance(value, (date, datetime)):
        parsed = value.date() if isinstance(value, datetime) else value
    else:
        raw = str(value).strip()
        try:
            parsed = date.fromisoformat(raw)
        except ValueError:
            try:
                parsed = datetime.strptime(raw, "%B %d, %Y").date()
            except ValueError as exc:
                raise ValueError(f"Invalid date: {raw}") from exc
    return f"{parsed.strftime('%B')} {parsed.day}, {parsed.year}"


def utility_defaults(municipality: str | None, is_multiplex: bool) -> dict[str, str | None]:
    landlord_water = (municipality or "").casefold().strip() != "winnipeg" or is_multiplex
    return {
        "services_tenant_pays": LANDLORD_WATER_SERVICES if landlord_water else TENANT_SERVICES,
        "services_landlord_pays": LANDLORD_SERVICES,
        "utility_exceptions": "water and sewer" if landlord_water else None,
    }


def build_context(raw: dict[str, Any], property: RentalProperty, *, renewal: bool = False) -> dict[str, Any]:
    """Build a complete, canonical template snapshot from editable form values."""
    context: dict[str, Any] = {key: raw.get(key) or None for key in OPTIONAL}
    tenants = raw.get("tenants") or []
    if not isinstance(tenants, list) or not tenants:
        raise ValueError("At least one tenant is required")
    normalized_tenants = []
    emails = set()
    for tenant in tenants:
        name = str(tenant.get("name") or "").strip()
        email = str(tenant.get("email") or "").strip()
        if not name or not EMAIL.fullmatch(email):
            raise ValueError("Every tenant needs a name and valid email")
        if email.casefold() in emails:
            raise ValueError("Tenant emails must be unique")
        emails.add(email.casefold())
        normalized_tenants.append({"name": name, "email": email})
    context["tenants"] = normalized_tenants
    context["tenant_names"] = " & ".join(tenant["name"] for tenant in normalized_tenants)
    city = (property.municipality or property.city or "").strip()
    context["unit_address"] = f"{property.street_address}, {city}, MB" if city else f"{property.street_address}, MB"
    context["is_condo"] = property.is_condo
    context["furniture_provided"] = bool(raw.get("furniture_provided", False))

    term = raw.get("term") or ("fixed" if raw.get("fixed_start") or raw.get("fixed_end") else "periodic")
    if term not in {"fixed", "periodic"}:
        raise ValueError("Choose a fixed or periodic term")
    if term == "fixed":
        if raw.get("periodic_start") or raw.get("periodic_period"):
            raise ValueError("Fill in exactly one term type")
        context["fixed_start"] = long_date(raw.get("fixed_start"))
        context["fixed_end"] = long_date(raw.get("fixed_end"))
        if not context["fixed_start"] or not context["fixed_end"]:
            raise ValueError("Fixed term requires start and end dates")
        if datetime.strptime(context["fixed_end"], "%B %d, %Y") <= datetime.strptime(context["fixed_start"], "%B %d, %Y"):
            raise ValueError("Fixed term end must be after its start")
        context["periodic_start"] = context["periodic_period"] = None
    else:
        if raw.get("fixed_start") or raw.get("fixed_end"):
            raise ValueError("Fill in exactly one term type")
        context["periodic_start"] = long_date(raw.get("periodic_start"))
        context["periodic_period"] = raw.get("periodic_period") or None
        if not context["periodic_start"] or not context["periodic_period"]:
            raise ValueError("Periodic term requires start date and period")
        context["fixed_start"] = context["fixed_end"] = None

    for key in ("security_deposit_date", "pet_deposit_date", "guideline_increase_date", "above_guideline_date"):
        context[key] = long_date(raw.get(key))
    for key in ("basic_rent", "parking_amount", "other_charge_amount", "rent_discount", "security_deposit_amount",
                "pet_deposit_amount", "above_guideline_rent", "discount_increase_amount", "discount_reduced_amount", "agi_max_amount"):
        context[key] = money(raw.get(key), optional=key != "basic_rent")
    basic = Decimal(context["basic_rent"].replace(",", ""))
    if basic <= 0:
        raise ValueError("Basic rent must be greater than zero")
    payable = basic + sum(Decimal(context[key].replace(",", "")) for key in ("parking_amount", "other_charge_amount") if context[key])
    discount = Decimal(context["rent_discount"].replace(",", "")) if context["rent_discount"] else Decimal("0")
    if discount > payable:
        raise ValueError("Discount cannot exceed rent payable")
    context["rent_payable"] = money(payable)
    context["actual_rent"] = money(payable - discount)
    if context["security_deposit_amount"] and Decimal(context["security_deposit_amount"].replace(",", "")) > payable / 2:
        raise ValueError("Security deposit exceeds half of rent payable")
    if context["pet_deposit_amount"] and Decimal(context["pet_deposit_amount"].replace(",", "")) > payable:
        raise ValueError("Pet deposit exceeds one month's rent payable")
    if context["discount_change"] not in {None, "same", "reduced", "removed", "agi"}:
        raise ValueError("Invalid discount change")
    if renewal and discount and not context["discount_change"]:
        raise ValueError("Discount change is required for a renewal with a discount")
    context["rent_due_day"] = str(raw.get("rent_due_day") or "first")
    context["rent_period"] = str(raw.get("rent_period") or "month")
    defaults = utility_defaults(property.municipality or property.city, property.is_multiplex)
    defaults.update(property.lease_utility_override or {})
    for key, value in defaults.items():
        context[key] = raw[key] if key in raw else value
    if not context["services_tenant_pays"]:
        raise ValueError("Tenant services are required")
    return context
