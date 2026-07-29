from datetime import UTC, datetime

from sqlalchemy import select

from app.celery_app import celery
from app.config import get_settings
from app.db import SessionLocal
from app.integrations.gmail import GmailClient
from app.integrations.whatsapp import WhatsAppClient
from app.models import GmailWatchState, Reminder, ReminderStatus, Task, TaskStatus, User
from app.services.email_events import ingest_gmail_message
from app.services.tasks import advance_recurring_task
from app.services.time import format_local

settings = get_settings()


@celery.task(
    name="app.worker.send_verification_email",
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=5,
)
def send_verification_email(recipient: str, code: str, language: str) -> None:
    subject = "Код подтверждения TaskMate" if language == "ru" else "TaskMate verification code"
    body = (
        f"Ваш код подтверждения: {code}\nКод скоро истечет."
        if language == "ru"
        else f"Your verification code is: {code}\nThe code expires shortly."
    )
    GmailClient(settings).send_email(recipient, subject, body)


@celery.task(
    name="app.worker.process_gmail_message",
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=5,
)
def process_gmail_message(message_id: str) -> None:
    message = GmailClient(settings).get_message(message_id)
    with SessionLocal() as db:
        _, recipient, prompt = ingest_gmail_message(db, message, settings)
        db.commit()
    if recipient and prompt:
        WhatsAppClient(settings).send_text(recipient, prompt)


@celery.task(name="app.worker.process_gmail_history")
def process_gmail_history(email_address: str, notification_history_id: str) -> None:
    gmail = GmailClient(settings)
    with SessionLocal() as db:
        state = db.get(GmailWatchState, email_address)
        if not state:
            db.add(
                GmailWatchState(
                    email_address=email_address,
                    history_id=notification_history_id,
                )
            )
            db.commit()
            return
        start_history_id = state.history_id
    message_ids, latest_history_id = gmail.history(start_history_id)
    for message_id in message_ids:
        process_gmail_message.delay(message_id)
    with SessionLocal() as db:
        state = db.get(GmailWatchState, email_address)
        state.history_id = latest_history_id or notification_history_id
        db.commit()


@celery.task(name="app.worker.dispatch_due_reminders")
def dispatch_due_reminders() -> int:
    now = datetime.now(UTC)
    sent = 0
    with SessionLocal() as db:
        ids = list(
            db.scalars(
                select(Reminder.id)
                .join(Task)
                .where(
                    Reminder.status == ReminderStatus.PENDING,
                    Reminder.scheduled_at <= now,
                    Task.status == TaskStatus.PENDING,
                )
                .with_for_update(skip_locked=True)
                .limit(100)
            ).all()
        )
        for reminder_id in ids:
            reminder = db.get(Reminder, reminder_id)
            task = db.get(Task, reminder.task_id)
            user = db.get(User, task.user_id)
            body = (
                f"Задача: {task.title}, срок {format_local(task.due_at, task.timezone, 'ru')}"
                if user.language.value == "ru"
                else f"Task: {task.title}, due {format_local(task.due_at, task.timezone, 'en')}"
            )
            try:
                WhatsAppClient(settings).send_reminder(user, body)
                reminder.status = ReminderStatus.SENT
                reminder.sent_at = now
                sent += 1
            except Exception as exc:
                reminder.attempts += 1
                reminder.last_error = str(exc)[:1000]
                if reminder.attempts >= 5:
                    reminder.status = ReminderStatus.FAILED
        db.commit()
    return sent


@celery.task(name="app.worker.advance_recurring_tasks")
def advance_recurring_tasks() -> int:
    now = datetime.now(UTC)
    advanced = 0
    with SessionLocal() as db:
        tasks = list(
            db.scalars(
                select(Task)
                .where(
                    Task.status == TaskStatus.PENDING,
                    Task.recurrence.is_not(None),
                    Task.due_at <= now,
                )
                .with_for_update(skip_locked=True)
                .limit(100)
            ).all()
        )
        for task in tasks:
            advanced += int(advance_recurring_task(db, task, now=now))
        db.commit()
    return advanced


@celery.task(name="app.worker.renew_gmail_watch")
def renew_gmail_watch() -> dict:
    gmail = GmailClient(settings)
    response = gmail.watch()
    profile = gmail.profile()
    expiration = response.get("expiration")
    with SessionLocal() as db:
        db.merge(
            GmailWatchState(
                email_address=profile["emailAddress"].casefold(),
                history_id=str(response["historyId"]),
                expiration_at=(
                    datetime.fromtimestamp(int(expiration) / 1000, UTC) if expiration else None
                ),
            )
        )
        db.commit()
    return response
