from celery import Celery

from app.config import get_settings

settings = get_settings()
celery = Celery(
    "taskmate",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.worker"],
)
celery.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    beat_schedule={
        "dispatch-due-reminders": {
            "task": "app.worker.dispatch_due_reminders",
            "schedule": 30.0,
        },
        "gmail-watch-renewal": {
            "task": "app.worker.renew_gmail_watch",
            "schedule": 86400.0,
        },
        "advance-recurring-tasks": {
            "task": "app.worker.advance_recurring_tasks",
            "schedule": 60.0,
        },
    },
)
