from app.services.maintenance.emergencies import run_escalation_sync
from app.services.maintenance.jobs import run_digest_sync, run_sla_watch_sync
from app.services.maintenance.slack.dispatcher import run_dispatch_sync
from app.services.maintenance.sms.outbound import run_sender_sync
from app.workers.celery_app import celery_app


@celery_app.task(name="maintenance.send_due_sms")
def send_due_sms() -> int:
    return run_sender_sync()


@celery_app.task(name="maintenance.dispatch_slack_outbox")
def dispatch_slack_outbox() -> int:
    return run_dispatch_sync()


@celery_app.task(name="maintenance.watch_sla")
def watch_sla() -> int:
    return run_sla_watch_sync()


@celery_app.task(name="maintenance.escalate_emergencies")
def escalate_emergencies() -> int:
    return run_escalation_sync()


@celery_app.task(name="maintenance.morning_digest")
def morning_digest() -> int:
    return run_digest_sync()
