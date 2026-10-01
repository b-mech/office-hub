"""Report whether current rental tenant phones can be normalized to E.164.

This command is read-only unless --apply is supplied. It never prints full phone
numbers; failures are identified by tenant ID and last four digits only.
"""
from __future__ import annotations

import argparse
import asyncio

from sqlalchemy import select

from app.core.database import AsyncSessionLocal, engine
from app.models.rentals import RentalTenant
from app.services.maintenance.errors import InvalidPhoneError
from app.services.maintenance.phones import normalize_phone


async def run(apply: bool) -> int:
    normalized = 0
    unchanged = 0
    failures: list[tuple[int, str]] = []
    async with AsyncSessionLocal() as db:
        tenants = list(
            (
                await db.scalars(
                    select(RentalTenant)
                    .where(RentalTenant.phone.is_not(None), RentalTenant.phone != "")
                    .order_by(RentalTenant.id)
                )
            ).all()
        )
        for tenant in tenants:
            assert tenant.phone is not None
            try:
                result = normalize_phone(tenant.phone)
            except InvalidPhoneError:
                failures.append((tenant.id, "".join(character for character in tenant.phone if character.isdigit())[-4:]))
                continue
            if result == tenant.phone:
                unchanged += 1
            else:
                normalized += 1
                if apply:
                    tenant.phone = result
        if apply:
            await db.commit()

    print(f"mode={'apply' if apply else 'report-only'} normalized={normalized} unchanged={unchanged} failed={len(failures)}")
    for tenant_id, last_four in failures:
        print(f"failed tenant_id={tenant_id} phone_last4={last_four or 'none'}")
    await engine.dispose()
    return 1 if failures else 0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Write normalized values after reporting")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(run(args.apply)))


if __name__ == "__main__":
    main()
