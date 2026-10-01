"""One-off backfill of realtor contact fields for existing presale Sale OTPs."""
from __future__ import annotations

import asyncio

from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.core import Lot, SaleType
from app.models.documents import Ingestion
from app.models.sales import SalesAgreement
from app.modules.costbook import models as _costbook_models  # noqa: F401 - registers ORM relationships
from app.services.extraction.service import get_extraction_service


async def main() -> None:
    extraction_service = get_extraction_service()
    updated = 0
    async with AsyncSessionLocal() as db:
        lots = list((await db.scalars(select(Lot).where(Lot.sale_type == SaleType.PRESALE))).all())
        for lot in lots:
            if lot.realtor_name and lot.realtor_email:
                continue
            sale = await db.scalar(
                select(SalesAgreement)
                .where(SalesAgreement.lot_id == lot.id)
                .order_by(SalesAgreement.created_at.desc())
                .limit(1)
            )
            if sale is None:
                continue
            ingestion = await db.scalar(
                select(Ingestion)
                .where(Ingestion.document_id == sale.document_id)
                .order_by(Ingestion.completed_at.desc())
                .limit(1)
            )
            if ingestion is None or not ingestion.ocr_text:
                continue
            result = await asyncio.to_thread(extraction_service.extract, "sale_otp", ingestion.ocr_text)
            agreement = result.extracted_payload.get("agreement", {})
            if not isinstance(agreement, dict):
                continue
            lot.realtor_name = str(
                agreement.get("realtor_name")
                or agreement.get("buyers_realtor_name")
                or agreement.get("sellers_realtor_name")
                or ""
            ).strip() or lot.realtor_name
            lot.realtor_email = str(
                agreement.get("realtor_email")
                or agreement.get("buyers_realtor_email")
                or agreement.get("sellers_realtor_email")
                or ""
            ).strip().casefold() or lot.realtor_email
            lot.realtor_brokerage = str(
                agreement.get("realtor_brokerage")
                or agreement.get("buyers_brokerage")
                or agreement.get("sellers_brokerage")
                or ""
            ).strip() or lot.realtor_brokerage
            updated += 1
        await db.commit()
    print(f"Updated realtor details for {updated} presale lots.")


if __name__ == "__main__":
    asyncio.run(main())
