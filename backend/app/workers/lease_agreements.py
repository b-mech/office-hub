"""Poll open lease envelopes and finish Box filing through the existing Redis worker."""
from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.rentals import LeaseAgreement
from app.services.lease_workflow import file_completed, poll
from app.services.lease_rendering import render
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="leases.render")
def render_lease(lease_id: str, context: dict) -> tuple[str, str]:
    return render(lease_id, context)


async def _poll_all() -> None:
    async with AsyncSessionLocal() as db:
        lease_ids = (await db.scalars(select(LeaseAgreement.id).where(
            LeaseAgreement.status.in_(["sent", "delivered", "completed"]),
            LeaseAgreement.docusign_envelope_id.is_not(None)))).all()
    for lease_id in lease_ids:
        async with AsyncSessionLocal() as db:
            lease = await db.get(LeaseAgreement, lease_id)
            if lease is None:
                continue
            if lease.status == "completed" and lease.signed_pdf_box_file_id:
                continue
            try:
                if lease.status == "completed":
                    await file_completed(db, lease)
                else:
                    await poll(db, lease)
            except Exception:
                await db.rollback()
                logger.exception("Lease envelope poll or filing failed for %s", lease.id)


@celery_app.task(name="leases.poll_open_envelopes")
def poll_open_envelopes() -> None:
    asyncio.run(_poll_all())


@celery_app.task(name="leases.process_envelope")
def process_envelope(envelope_id: str) -> None:
    async def run() -> None:
        async with AsyncSessionLocal() as db:
            lease = await db.scalar(select(LeaseAgreement).where(LeaseAgreement.docusign_envelope_id == envelope_id))
            if lease is not None:
                await poll(db, lease)
    asyncio.run(run())
