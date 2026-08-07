import asyncio

from app.core.database import AsyncSessionLocal
from app.services.quickbooks import reconcile_open_invoices
from app.workers.celery_app import celery_app


@celery_app.task(name="change_orders.reconcile_qbo_invoices")
def reconcile_qbo_invoices() -> int:
    return asyncio.run(_reconcile())


async def _reconcile() -> int:
    async with AsyncSessionLocal() as db:
        return await reconcile_open_invoices(db)
