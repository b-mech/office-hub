from celery import Celery
from celery.schedules import crontab

from app.core.config import settings

celery_app = Celery(
    "office_hub",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.workers.qbo_reconciliation", "app.workers.presales", "app.workers.maintenance"],
)
celery_app.conf.timezone = settings.timezone
celery_app.conf.task_always_eager = settings.celery_task_always_eager or settings.environment.casefold() in {
    "test",
    "testing",
}
celery_app.conf.beat_schedule = {
    "maintenance-send-due-sms": {"task": "maintenance.send_due_sms", "schedule": 5.0},
    "reconcile-qbo-change-order-invoices-morning": {"task": "change_orders.reconcile_qbo_invoices", "schedule": crontab(hour=9, minute=30)},
    "reconcile-qbo-change-order-invoices-afternoon": {"task": "change_orders.reconcile_qbo_invoices", "schedule": crontab(hour=15, minute=30)},
    "presale-approval-letter-expiry-reminders": {"task": "presales.expiry_reminders", "schedule": crontab(hour=8, minute=0)},
}
