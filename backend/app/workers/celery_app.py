from celery import Celery
from celery.schedules import crontab

from app.core.config import settings

celery_app = Celery("office_hub", broker=settings.redis_url, backend=settings.redis_url, include=["app.workers.qbo_reconciliation"])
celery_app.conf.timezone = "America/Winnipeg"
celery_app.conf.beat_schedule = {
    "reconcile-qbo-change-order-invoices-morning": {"task": "change_orders.reconcile_qbo_invoices", "schedule": crontab(hour=9, minute=30)},
    "reconcile-qbo-change-order-invoices-afternoon": {"task": "change_orders.reconcile_qbo_invoices", "schedule": crontab(hour=15, minute=30)},
}
