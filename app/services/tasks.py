import re
from datetime import UTC, datetime, timedelta

from dateutil.relativedelta import relativedelta
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models import Priority, Reminder, ReminderStatus, Task, TaskOccurrence, TaskStatus, User
from app.schemas import Intent
from app.services.time import as_utc, format_local, parse_future_datetime, period_bounds


class TaskError(ValueError):
    pass


def schedule_reminders(
    db: Session, task: Task, minutes: list[int], *, now: datetime | None = None
) -> None:
    now = now or datetime.now(UTC)
    db.execute(
        update(Reminder)
        .where(Reminder.task_id == task.id, Reminder.status == ReminderStatus.PENDING)
        .values(status=ReminderStatus.CANCELLED)
    )
    if not task.due_at:
        return
    # A task always produces a due-time notification in addition to advance warnings.
    for value in sorted(set(minutes) | {0}, reverse=True):
        scheduled = task.due_at - timedelta(minutes=value)
        if scheduled > now:
            db.add(
                Reminder(
                    task=task,
                    minutes_before=value,
                    scheduled_at=scheduled,
                    occurrence_at=task.due_at,
                )
            )


def next_occurrence(value: datetime, recurrence: dict) -> datetime:
    frequency = recurrence["frequency"]
    interval = int(recurrence.get("interval", 1))
    if frequency == "daily":
        return value + timedelta(days=interval)
    if frequency == "weekdays":
        candidate = value + timedelta(days=1)
        while candidate.weekday() >= 5:
            candidate += timedelta(days=1)
        return candidate
    if frequency == "weekly":
        return value + timedelta(weeks=interval)
    if frequency == "monthly":
        return value + relativedelta(months=interval)
    if frequency == "interval":
        return value + timedelta(days=interval)
    raise TaskError(f"Unsupported recurrence: {frequency}")


def advance_recurring_task(db: Session, task: Task, *, now: datetime | None = None) -> bool:
    now = now or datetime.now(UTC)
    if not task.recurrence or not task.due_at or as_utc(task.due_at) > now:
        return False
    previous_due = as_utc(task.due_at)
    db.add(TaskOccurrence(task_id=task.id, occurrence_at=previous_due))
    candidate = next_occurrence(previous_due, task.recurrence)
    while candidate <= now:
        candidate = next_occurrence(candidate, task.recurrence)
    task.due_at = candidate
    minutes = sorted({item.minutes_before for item in task.reminders}, reverse=True)
    schedule_reminders(db, task, minutes, now=now)
    return True


def create_task(db: Session, user: User, intent: Intent, *, now: datetime | None = None) -> Task:
    if not intent.title:
        raise TaskError("Task title is required")
    due_at = None
    if intent.when_text and not intent.no_due:
        due_at = parse_future_datetime(
            intent.when_text, user.timezone or "UTC", now=now, language=user.language.value
        )
    task = Task(
        user=user,
        title=intent.title[:500],
        due_at=due_at,
        timezone=user.timezone or "UTC",
        priority=intent.priority,
        recurrence=intent.recurrence.model_dump() if intent.recurrence else None,
    )
    db.add(task)
    db.flush()
    schedule_reminders(db, task, intent.reminders or user.default_reminders, now=now)
    return task


def find_tasks(db: Session, user: User, reference: str) -> list[Task]:
    query = select(Task).where(Task.user_id == user.id, Task.status == TaskStatus.PENDING)
    if len(reference) >= 8 and "-" in reference:
        query = query.where(Task.id == reference)
    else:
        query = query.where(Task.title.ilike(f"%{reference}%"))
    return list(db.scalars(query.order_by(Task.due_at.asc().nullslast())).all())


def reschedule_task(
    db: Session, user: User, task: Task, when_text: str, *, now: datetime | None = None
) -> None:
    now = now or datetime.now(UTC)
    relative = when_text.casefold().strip()
    relative_match = re.fullmatch(
        r"(?:(\d+)\s*)?"
        r"(минут(?:у|ы)?|час(?:а|ов)?|д(?:ень|ня|ней)|minute|minutes|hour|hours|day|days)"
        r"\s+(позже|раньше|later|earlier)",
        relative,
    )
    if relative in {"полчаса позже", "half an hour later"}:
        delta = timedelta(minutes=30)
    elif relative in {"полчаса раньше", "half an hour earlier"}:
        delta = -timedelta(minutes=30)
    elif relative_match:
        amount = int(relative_match.group(1) or 1)
        unit = relative_match.group(2)
        multiplier = (
            1
            if unit.startswith(("минут", "minute"))
            else 60
            if unit.startswith(("час", "hour"))
            else 1440
        )
        direction = -1 if relative_match.group(3) in {"раньше", "earlier"} else 1
        delta = timedelta(minutes=amount * multiplier * direction)
    else:
        delta = None
    if delta is not None:
        if not task.due_at:
            raise TaskError("Cannot relatively reschedule a task without a due date")
        target = as_utc(task.due_at) + delta
        if target <= now:
            raise TaskError("New task time must be in the future")
        task.due_at = target
    else:
        task.due_at = parse_future_datetime(
            when_text, user.timezone or "UTC", now=now, language=user.language.value
        )
    task.timezone = user.timezone or "UTC"
    schedule_reminders(db, task, [r.minutes_before for r in task.reminders], now=now)


def complete_task(task: Task, *, now: datetime | None = None) -> None:
    task.status = TaskStatus.COMPLETED
    task.completed_at = now or datetime.now(UTC)
    for reminder in task.reminders:
        if reminder.status == ReminderStatus.PENDING:
            reminder.status = ReminderStatus.CANCELLED


def summary(db: Session, user: User, period: str, *, now: datetime | None = None) -> str:
    now = now or datetime.now(UTC)
    start, end = period_bounds(period, user.timezone or "UTC", now)
    tasks = list(
        db.scalars(
            select(Task).where(
                Task.user_id == user.id,
                Task.status != TaskStatus.CANCELLED,
            )
        ).all()
    )
    overdue = [
        t for t in tasks if t.status == TaskStatus.PENDING and t.due_at and as_utc(t.due_at) < now
    ]
    active = [
        t
        for t in tasks
        if t.status == TaskStatus.PENDING
        and t.due_at
        and now <= as_utc(t.due_at) < end
    ]
    completed = [
        t
        for t in tasks
        if t.status == TaskStatus.COMPLETED
        and t.completed_at
        and start <= as_utc(t.completed_at) < end
    ]
    no_due = [t for t in tasks if t.status == TaskStatus.PENDING and t.due_at is None]
    rank = {Priority.HIGH: 0, Priority.NORMAL: 1, Priority.LOW: 2}
    active.sort(key=lambda task: (rank[task.priority], as_utc(task.due_at)))
    overdue.sort(key=lambda task: (rank[task.priority], as_utc(task.due_at)))
    ru = user.language.value == "ru"
    lines = [("Сводка" if ru else "Summary") + f": {period}"]
    sections = [
        ("Просрочено" if ru else "Overdue", overdue),
        ("Предстоит" if ru else "Upcoming", active),
        ("Выполнено" if ru else "Completed", completed),
        ("Без срока" if ru else "No due date", no_due),
    ]
    icons = {Priority.HIGH: "🔴", Priority.NORMAL: "🟡", Priority.LOW: "🟢"}
    for name, values in sections:
        lines.append(f"\n{name} ({len(values)}):")
        lines.extend(
            f"{icons[item.priority]} {item.title} — "
            f"{format_local(item.due_at, item.timezone, user.language.value)}"
            for item in values
        )
        if not values:
            lines.append("—")
    return "\n".join(lines)
