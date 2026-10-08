"""Create or remove the staging-only maintenance phone-flow test fixture.

Every owned row has an explicit TEST DATA marker or belongs only to a marked
record. The seed path is idempotent; ``--remove`` deletes the same fixture.
No phone number is ever printed.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import delete, or_, select


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPOSITORY_ROOT / "backend"
sys.path.insert(0, str(BACKEND_ROOT))
load_dotenv(REPOSITORY_ROOT / ".env.staging")

from app.core.config import settings  # noqa: E402
from app.core.database import AsyncSessionLocal  # noqa: E402
from app.models.core import User, UserRole  # noqa: E402
from app.models.maintenance import MaintOnCall, MaintTicket  # noqa: E402
from app.models.rentals import (  # noqa: E402
    RentalLease,
    RentalLeaseTenant,
    RentalProperty,
    RentalTenant,
    RentalUnit,
)
from app.services.maintenance.phones import normalize_phone  # noqa: E402


TEST_MARKER = "[TEST DATA: maintenance-phone-flow]"
STAFF_EMAIL = "nicholas.maintenance-phone-test@invalid.example"
STAFF_NAME = f"Nicholas {TEST_MARKER}"
TENANT_EMAIL = "tenant.maintenance-phone-test@invalid.example"
TENANT_NAME = f"Phone Flow Tenant {TEST_MARKER}"
TENANT_PHONE_E164 = "+12049961540"
TEST_TICKET_NUMBER = "MT-00001"
LEASE_NOTES = f"{TEST_MARKER} Idempotent staging fixture; remove with seed script --remove."


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tenant-phone",
        default=TENANT_PHONE_E164,
        help="Second allowlisted E.164 test number",
    )
    parser.add_argument("--staff-phone", help="Existing allowlisted E.164 number for Nicholas")
    parser.add_argument("--property-id", type=int, help="Optional real staging rental property ID")
    parser.add_argument("--remove", action="store_true", help="Remove the owned test fixture")
    return parser.parse_args()


def _staff_phone(tenant_phone: str, requested: str | None, existing: User | None) -> str:
    allowlisted = settings.staging_sms_allowlist_values
    if requested:
        normalized = normalize_phone(requested)
        if normalized not in allowlisted:
            raise SystemExit("--staff-phone must already be in STAGING_SMS_ALLOWLIST")
        return normalized
    if existing and existing.phone_e164 in allowlisted:
        return str(existing.phone_e164)
    candidates = sorted(value for value in allowlisted if value != tenant_phone)
    if len(candidates) != 1:
        raise SystemExit("Specify --staff-phone when the existing allowlist is not unambiguous")
    return candidates[0]


async def _real_unit(db, property_id: int | None) -> tuple[RentalProperty, RentalUnit, RentalLease]:
    today = date.today()
    statement = (
        select(RentalProperty, RentalUnit, RentalLease)
        .join(RentalUnit, RentalUnit.property_id == RentalProperty.id)
        .join(RentalLease, RentalLease.unit_id == RentalUnit.id)
        .where(
            RentalLease.status.in_(("active", "month_to_month")),
            or_(RentalLease.lease_end.is_(None), RentalLease.lease_end >= today),
            or_(RentalLease.lease_notes.is_(None), RentalLease.lease_notes != LEASE_NOTES),
        )
        .order_by(RentalProperty.id, RentalUnit.id, RentalLease.id)
        .limit(1)
    )
    if property_id is not None:
        statement = statement.where(RentalProperty.id == property_id)
    row = (await db.execute(statement)).first()
    if row is None:
        raise SystemExit("No real staging property with an active lease was found")
    return row


async def seed(args: argparse.Namespace) -> dict[str, object]:
    tenant_phone = normalize_phone(args.tenant_phone)
    if tenant_phone not in settings.staging_sms_allowlist_values:
        raise SystemExit("The tenant phone must already be in STAGING_SMS_ALLOWLIST")

    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        user = await db.scalar(select(User).where(User.email == STAFF_EMAIL))
        staff_phone = _staff_phone(tenant_phone, args.staff_phone, user)
        if user is None:
            user = User(
                org_id=settings.default_org_id,
                email=STAFF_EMAIL,
                full_name=STAFF_NAME,
                role=UserRole.ADMIN,
                is_active=True,
                permissions={},
                phone_e164=staff_phone,
            )
            db.add(user)
            await db.flush()
        else:
            user.full_name = STAFF_NAME
            user.role = UserRole.ADMIN
            user.is_active = True
            user.phone_e164 = staff_phone

        on_call = await db.scalar(
            select(MaintOnCall).where(
                MaintOnCall.user_id == user.id,
                MaintOnCall.is_backup.is_(False),
            )
        )
        if on_call is None:
            on_call = MaintOnCall(user_id=user.id, is_backup=False)
            db.add(on_call)
        on_call.starts_at = now - timedelta(minutes=1)
        on_call.ends_at = now + timedelta(days=7)

        tenant = await db.scalar(select(RentalTenant).where(RentalTenant.email == TENANT_EMAIL))
        existing_test_lease = await db.scalar(
            select(RentalLease).where(RentalLease.lease_notes == LEASE_NOTES)
        )
        if existing_test_lease is None:
            rental_property, unit, source_lease = await _real_unit(db, args.property_id)
        else:
            unit = await db.get(RentalUnit, existing_test_lease.unit_id)
            if unit is None:
                raise SystemExit("The test lease references a missing rental unit")
            rental_property = await db.get(RentalProperty, unit.property_id)
            if rental_property is None:
                raise SystemExit("The test lease references a missing rental property")
            source_lease = existing_test_lease

        if tenant is None:
            tenant = RentalTenant(
                full_name=TENANT_NAME,
                phone=tenant_phone,
                email=TENANT_EMAIL,
                sms_opted_out=False,
            )
            db.add(tenant)
            await db.flush()
        else:
            tenant.full_name = TENANT_NAME
            tenant.phone = tenant_phone
            tenant.sms_opted_out = False

        lease = existing_test_lease
        if lease is None:
            lease = RentalLease(
                unit_id=unit.id,
                rent=source_lease.rent,
                lease_start=date.today(),
                lease_end=date.today() + timedelta(days=30),
                status="active",
                lease_notes=LEASE_NOTES,
            )
            db.add(lease)
            await db.flush()
        else:
            lease.status = "active"
            lease.lease_start = date.today()
            lease.lease_end = date.today() + timedelta(days=30)
            lease.lease_notes = LEASE_NOTES

        link = await db.get(RentalLeaseTenant, (lease.id, tenant.id))
        if link is None:
            db.add(
                RentalLeaseTenant(
                    lease_id=lease.id,
                    tenant_id=tenant.id,
                    is_primary_contact=True,
                )
            )
        else:
            link.is_primary_contact = True

        test_ticket = await db.scalar(
            select(MaintTicket).where(
                MaintTicket.number == TEST_TICKET_NUMBER,
                MaintTicket.lease_id == lease.id,
            )
        )
        if test_ticket is not None:
            test_ticket.reporter_phone_e164 = tenant_phone
        await db.commit()
        return {
            "action": "seeded",
            "staff_user_id": str(user.id),
            "on_call_id": str(on_call.id),
            "tenant_id": tenant.id,
            "lease_id": lease.id,
            "unit_id": unit.id,
            "property_id": rental_property.id,
            "property_address": rental_property.street_address,
            "test_ticket_number": test_ticket.number if test_ticket else None,
            "on_call_starts_at": on_call.starts_at.isoformat(),
            "on_call_ends_at": on_call.ends_at.isoformat(),
        }


async def remove() -> dict[str, object]:
    async with AsyncSessionLocal() as db:
        user = await db.scalar(select(User).where(User.email == STAFF_EMAIL))
        tenant = await db.scalar(select(RentalTenant).where(RentalTenant.email == TENANT_EMAIL))
        lease = await db.scalar(select(RentalLease).where(RentalLease.lease_notes == LEASE_NOTES))
        if user is not None:
            await db.execute(delete(MaintOnCall).where(MaintOnCall.user_id == user.id))
        if tenant is not None and lease is not None:
            await db.execute(
                delete(RentalLeaseTenant).where(
                    RentalLeaseTenant.lease_id == lease.id,
                    RentalLeaseTenant.tenant_id == tenant.id,
                )
            )
        if lease is not None:
            await db.delete(lease)
        if tenant is not None:
            await db.delete(tenant)
        if user is not None:
            await db.delete(user)
        await db.commit()
        return {
            "action": "removed",
            "staff_user_id": str(user.id) if user else None,
            "on_call_removed": user is not None,
            "tenant_id": tenant.id if tenant else None,
            "lease_id": lease.id if lease else None,
        }


async def main() -> None:
    args = _arguments()
    if not settings.is_staging:
        raise SystemExit("Refusing to run: ENVIRONMENT must be staging")
    result = await remove() if args.remove else await seed(args)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    asyncio.run(main())
