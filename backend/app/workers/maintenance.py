from app.services.maintenance.sms.outbound import run_sender_sync
from app.workers.celery_app import celery_app


@celery_app.task(name="maintenance.send_due_sms")
def send_due_sms() -> int:
    return run_sender_sync()
