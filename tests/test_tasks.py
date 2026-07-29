from datetime import UTC, datetime, timedelta

from app.models import Language, Priority, ReminderStatus, Task, TaskStatus, User
from app.schemas import Intent
from app.services.tasks import (
    advance_recurring_task,
    complete_task,
    create_task,
    reschedule_task,
    summary,
)


def make_user(db):
    user = User(
        whatsapp_id="77001234567",
        language=Language.RU,
        timezone="Asia/Almaty",
        onboarding_step="complete",
        default_reminders=[1440, 60],
    )
    db.add(user)
    db.flush()
    return user


def test_create_and_reschedule_cancels_old_reminders(db):
    user = make_user(db)
    now = datetime(2026, 7, 28, 10, tzinfo=UTC)
    task = create_task(
        db,
        user,
        Intent(action="create", title="Отчет", when_text="через 2 дня"),
        now=now,
    )
    assert len(task.reminders) == 3
    old_ids = {item.id for item in task.reminders}
    reschedule_task(db, user, task, "через 3 дня", now=now)
    db.flush()
    cancelled = [item for item in task.reminders if item.id in old_ids]
    assert all(item.status == ReminderStatus.CANCELLED for item in cancelled)
    assert len([item for item in task.reminders if item.status == ReminderStatus.PENDING]) == 3


def test_complete_cancels_pending_reminders(db):
    user = make_user(db)
    now = datetime(2026, 7, 28, 10, tzinfo=UTC)
    task = create_task(
        db, user, Intent(action="create", title="Звонок", when_text="завтра"), now=now
    )
    complete_task(task, now=now)
    assert task.status == TaskStatus.COMPLETED
    assert all(reminder.status == ReminderStatus.CANCELLED for reminder in task.reminders)


def test_summary_orders_by_priority(db):
    user = make_user(db)
    now = datetime(2026, 7, 28, 10, tzinfo=UTC)
    db.add_all(
        [
            Task(
                user=user,
                title="Обычная",
                due_at=now + timedelta(hours=3),
                timezone=user.timezone,
                priority=Priority.NORMAL,
            ),
            Task(
                user=user,
                title="Важная",
                due_at=now + timedelta(hours=4),
                timezone=user.timezone,
                priority=Priority.HIGH,
            ),
        ]
    )
    db.flush()
    text = summary(db, user, "day", now=now)
    assert text.index("Важная") < text.index("Обычная")


def test_summary_does_not_repeat_overdue_as_upcoming(db):
    user = make_user(db)
    now = datetime(2026, 7, 28, 10, tzinfo=UTC)
    db.add(
        Task(
            user=user,
            title="Просроченная",
            due_at=now - timedelta(hours=1),
            timezone=user.timezone,
        )
    )
    db.flush()
    text = summary(db, user, "day", now=now)
    assert text.count("Просроченная") == 1


def test_task_always_has_due_time_reminder(db):
    user = make_user(db)
    now = datetime(2026, 7, 28, 10, tzinfo=UTC)
    task = create_task(
        db,
        user,
        Intent(action="create", title="Звонок", when_text="через 2 дня", reminders=[60]),
        now=now,
    )
    assert {item.minutes_before for item in task.reminders} == {60, 0}


def test_recurring_task_advances_past_now(db):
    user = make_user(db)
    now = datetime(2026, 7, 28, 10, tzinfo=UTC)
    task = Task(
        user=user,
        title="Daily standup",
        due_at=now - timedelta(days=2),
        timezone=user.timezone,
        recurrence={"frequency": "daily", "interval": 1},
    )
    db.add(task)
    db.flush()
    assert advance_recurring_task(db, task, now=now)
    assert task.due_at == now + timedelta(days=1)


def test_relative_reschedule_from_existing_due_time(db):
    user = make_user(db)
    now = datetime(2026, 7, 29, 7, 20, tzinfo=UTC)
    task = Task(
        user=user,
        title="позвонить Кале",
        due_at=datetime(2026, 7, 29, 8, 20, tzinfo=UTC),
        timezone=user.timezone,
    )
    db.add(task)
    db.flush()
    reschedule_task(db, user, task, "час позже", now=now)
    assert task.due_at == datetime(2026, 7, 29, 9, 20, tzinfo=UTC)
