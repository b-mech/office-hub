#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
from copy import deepcopy
from typing import Any
from uuid import UUID

from sqlalchemy import select

import app.models  # noqa: F401  # Register all ORM relationships for standalone execution.
import app.modules.costbook.models  # noqa: F401
from app.core.database import AsyncSessionLocal
from app.models.documents import DocType
from app.models.documents import Document
from app.models.documents import DocumentStatus
from app.models.documents import Extraction
from app.models.documents import Ingestion


CORRECTION_VERSION = "source-schedule-review-v2"


def _lot(
    *,
    block: str,
    lot_number: str,
    plan: str,
    civic_address: str,
    frontage_feet: float | None = None,
    lot_notes: str,
    purchase_price: int,
    deposit_1_amount: int | None = None,
) -> dict[str, Any]:
    street_number, street_name = civic_address.split(" ", 1)
    return {
        "block": block,
        "lot_number": lot_number,
        "plan": plan,
        "civic_address": civic_address,
        "street_number": street_number,
        "street_name": street_name,
        "frontage_metres": None,
        "frontage_feet": frontage_feet,
        "lot_notes": lot_notes,
        "purchase_price": purchase_price,
        "deposit_1_amount": deposit_1_amount,
        "deposit_2_amount": None,
        "deposit_2_due_date": None,
    }


CORRECTIONS: dict[UUID, list[dict[str, Any]]] = {
    UUID("f22836fe-6ae6-4ea3-9fc0-cb6c7af3c355"): [
        _lot(block="5", lot_number="11", plan="71499", civic_address="41 Woodland Way", frontage_feet=44.29, lot_notes="Title 3241883/1; Schedule A, Lot Draw 1", purchase_price=154900, deposit_1_amount=38725),
        _lot(block="5", lot_number="13", plan="71499", civic_address="49 Woodland Way", frontage_feet=44.29, lot_notes="Title 3241885/1; Schedule A, Lot Draw 1", purchase_price=154900, deposit_1_amount=38725),
        _lot(block="6", lot_number="5", plan="71499", civic_address="48 Woodland Way", frontage_feet=44.29, lot_notes="Title 3241907/1; Schedule A, Lot Draw 1", purchase_price=154900, deposit_1_amount=38725),
        _lot(block="6", lot_number="6", plan="71499", civic_address="56 Woodland Way", frontage_feet=44.29, lot_notes="Title 3241908/1; Schedule A, Lot Draw 1", purchase_price=154900, deposit_1_amount=38725),
        _lot(block="6", lot_number="8", plan="71499", civic_address="64 Woodland Way", frontage_feet=44.29, lot_notes="Title 3241910/1; Schedule A, Lot Draw 1", purchase_price=154900, deposit_1_amount=38725),
        _lot(block="6", lot_number="15", plan="71499", civic_address="29 Alder Row", frontage_feet=44.29, lot_notes="Title 3241918/1; Schedule A, Lot Draw 1", purchase_price=154900, deposit_1_amount=38725),
        _lot(block="9", lot_number="4", plan="71499", civic_address="24 Alder Row", frontage_feet=44.29, lot_notes="Title 3242071/1; back on to pond; Schedule A, Lot Draw 1", purchase_price=180900, deposit_1_amount=45225),
        _lot(block="14", lot_number="4", plan="71499", civic_address="65 Woodland Way", frontage_feet=44.29, lot_notes="Title 3242200/1; Schedule A, Lot Draw 1", purchase_price=154900, deposit_1_amount=38725),
        _lot(block="14", lot_number="11", plan="71499", civic_address="97 Woodland Way", frontage_feet=50.29, lot_notes="Title 3242208/1; backing on to creek; Schedule A, Lot Draw 1", purchase_price=178000, deposit_1_amount=44500),
        _lot(block="14", lot_number="12", plan="71499", civic_address="101 Woodland Way", frontage_feet=50.29, lot_notes="Title 3242209/1; backing on to creek; Schedule A, Lot Draw 1", purchase_price=178000, deposit_1_amount=44500),
    ],
    UUID("376c0803-f458-4f82-a180-d35c5367fb20"): [
        _lot(block="3", lot_number="3", plan="74032", civic_address="38 Morning Glory Way", lot_notes="Lot width 64.0; lot depth 174; Schedule A price list", purchase_price=179990),
        _lot(block="3", lot_number="5", plan="74032", civic_address="32 Morning Glory Way", lot_notes="Lot width 64.0; lot depth 183; Schedule A price list", purchase_price=179990),
        _lot(block="4", lot_number="38", plan="74032", civic_address="43 Morning Glory Way", lot_notes="Lot width 54.0; lot depth 151.0; Schedule A price list", purchase_price=144990),
        _lot(block="4", lot_number="40", plan="74032", civic_address="39 Morning Glory Way", lot_notes="Lot width 54.0; lot depth 135.6; Schedule A price list", purchase_price=144990),
        _lot(block="4", lot_number="41", plan="74032", civic_address="37 Morning Glory Way", lot_notes="Lot width 52.0; lot depth 131.2; Schedule A price list", purchase_price=134990),
        _lot(block="4", lot_number="42", plan="74032", civic_address="35 Morning Glory Way", lot_notes="Lot width 52.0; lot depth 131.2; Schedule A price list", purchase_price=134990),
        _lot(block="4", lot_number="43", plan="74032", civic_address="33 Morning Glory Way", lot_notes="Lot width 52.0; lot depth 131.2; Schedule A price list", purchase_price=134990),
        _lot(block="4", lot_number="44", plan="74032", civic_address="31 Morning Glory Way", lot_notes="Lot width 52.0; lot depth 131.2; Schedule A price list", purchase_price=134990),
        _lot(block="4", lot_number="45", plan="74032", civic_address="29 Morning Glory Way", lot_notes="Lot width 52.0; lot depth 131.2; Schedule A price list", purchase_price=134990),
        _lot(block="4", lot_number="46", plan="74032", civic_address="27 Morning Glory Way", lot_notes="Lot width 52.0; lot depth 131.4; Schedule A price list", purchase_price=134990),
        _lot(block="4", lot_number="47", plan="74032", civic_address="25 Morning Glory Way", lot_notes="Lot width 54.0; lot depth 136.4; Schedule A price list", purchase_price=144990),
        _lot(block="4", lot_number="48", plan="74032", civic_address="23 Morning Glory Way", lot_notes="Lot width 54.0; lot depth 148.9; Schedule A price list", purchase_price=144990),
    ],
}
NORMALIZE_EXISTING_DOCUMENT_IDS = {
    UUID("69097875-e4b6-4ea6-8c17-e01727123007"),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Stage source-schedule corrections for the targeted Land OTP reviews.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Create new extraction revisions. Without this flag, only print the proposed corrections.",
    )
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    async with AsyncSessionLocal() as db:
        document_ids = [*CORRECTIONS, *NORMALIZE_EXISTING_DOCUMENT_IDS]
        for document_id in document_ids:
            document = await db.get(Document, document_id)
            if document is None:
                raise RuntimeError(f"Document not found: {document_id}")
            if document.doc_type != DocType.LAND_OTP:
                raise RuntimeError(f"Document is not a Land OTP: {document_id}")
            if document.status != DocumentStatus.IN_REVIEW:
                raise RuntimeError(
                    f"Document is no longer in review ({document.status.value}): {document_id}"
                )

            ingestion = await db.scalar(
                select(Ingestion)
                .where(Ingestion.document_id == document_id)
                .order_by(Ingestion.completed_at.desc().nullslast())
                .limit(1)
            )
            if ingestion is None:
                raise RuntimeError(f"No ingestion found: {document_id}")

            existing_correction = await db.scalar(
                select(Extraction.id)
                .where(
                    Extraction.ingestion_id == ingestion.id,
                    Extraction.prompt_version == CORRECTION_VERSION,
                )
                .limit(1)
            )
            if existing_correction is not None:
                print(f"skip document={document_id} correction={existing_correction}")
                continue

            current = await db.scalar(
                select(Extraction)
                .where(Extraction.ingestion_id == ingestion.id)
                .order_by(Extraction.created_at.desc())
                .limit(1)
            )
            if current is None:
                raise RuntimeError(f"No extraction found: {document_id}")

            if document_id in CORRECTIONS:
                lots = deepcopy(CORRECTIONS[document_id])
            else:
                lots = deepcopy(current.extracted_payload.get("lots"))
                if not isinstance(lots, list):
                    raise RuntimeError(f"Extraction lots are not a list: {document_id}")
                for lot in lots:
                    if not isinstance(lot, dict):
                        raise RuntimeError(f"Extraction contains a non-object lot: {document_id}")
                    plan = lot.get("plan")
                    if isinstance(plan, str) and plan.casefold().startswith("plan "):
                        lot["plan"] = plan[5:].strip()

                requested = next(
                    (lot for lot in lots if lot.get("civic_address") == "53 Spruce Cove"),
                    None,
                )
                expected = {"block": "2", "lot_number": "30", "plan": "71499"}
                if requested is None or any(requested.get(key) != value for key, value in expected.items()):
                    raise RuntimeError(
                        "53 Spruce Cove does not match the verified Block 2, Lot 30, Plan 71499"
                    )

            print(f"document={document_id} rows={len(lots)}")
            for lot in lots:
                print(
                    f"  {lot['civic_address']}: Block {lot['block']}, "
                    f"Lot {lot['lot_number']}, Plan {lot['plan']}"
                )
            if not args.apply:
                continue

            payload = deepcopy(current.extracted_payload)
            payload["lots"] = lots
            confidences = {
                path: value
                for path, value in (current.field_confidences or {}).items()
                if not path.startswith("lots.")
            }
            low_confidence_fields = {
                path
                for path in (current.low_confidence_fields or [])
                if not path.startswith("lots.")
            }

            correction = Extraction(
                ingestion_id=ingestion.id,
                model_provider="manual",
                model_version=CORRECTION_VERSION,
                prompt_version=CORRECTION_VERSION,
                extracted_payload=payload,
                field_confidences=confidences,
                low_confidence_fields=sorted(low_confidence_fields),
            )
            db.add(correction)

        if args.apply:
            await db.commit()
            print("staged source-backed extraction revisions; document statuses remain in_review")
        else:
            print("dry run only; pass --apply to stage these review revisions")


if __name__ == "__main__":
    asyncio.run(main())
