import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def uuid_str() -> str:
    return str(uuid.uuid4())


def utc_now() -> datetime:
    return datetime.now(UTC)


class Language(str, enum.Enum):
    RU = "ru"
    EN = "en"


class Priority(str, enum.Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"


class TaskStatus(str, enum.Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class TaskKind(str, enum.Enum):
    TASK = "task"
    EVENT = "event"


class EmailStatus(str, enum.Enum):
    UNLINKED = "unlinked"
    NEEDS_DETAILS = "needs_details"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    FAILED = "failed"


class ReminderStatus(str, enum.Enum):
    PENDING = "pending"
    SENT = "sent"
    CANCELLED = "cancelled"
    FAILED = "failed"


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    whatsapp_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    language: Mapped[Language | None] = mapped_column(Enum(Language), nullable=True)
    timezone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    default_reminders: Mapped[list[int]] = mapped_column(JSON, default=lambda: [1440, 60])
    onboarding_step: Mapped[str] = mapped_column(String(40), default="language")
    last_inbound_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    emails: Mapped[list["UserEmail"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    tasks: Mapped[list["Task"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class UserEmail(Base):
    __tablename__ = "user_emails"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    otp_hash: Mapped[str | None] = mapped_column(String(128))
    otp_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    user: Mapped[User] = relationship(back_populates="emails")


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(500))
    description: Mapped[str | None] = mapped_column(Text)
    kind: Mapped[TaskKind] = mapped_column(Enum(TaskKind), default=TaskKind.TASK)
    status: Mapped[TaskStatus] = mapped_column(Enum(TaskStatus), default=TaskStatus.PENDING)
    priority: Mapped[Priority] = mapped_column(Enum(Priority), default=Priority.NORMAL)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    timezone: Mapped[str] = mapped_column(String(64))
    location: Mapped[str | None] = mapped_column(String(1000))
    organizer: Mapped[str | None] = mapped_column(String(320))
    source_email_id: Mapped[str | None] = mapped_column(ForeignKey("inbound_emails.id"))
    recurrence: Mapped[dict | None] = mapped_column(JSON)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    user: Mapped[User] = relationship(back_populates="tasks")
    reminders: Mapped[list["Reminder"]] = relationship(
        back_populates="task", cascade="all, delete-orphan"
    )

    __table_args__ = (Index("ix_tasks_user_status_due", "user_id", "status", "due_at"),)


class Reminder(Base):
    __tablename__ = "reminders"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), index=True)
    minutes_before: Mapped[int] = mapped_column(Integer)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    occurrence_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[ReminderStatus] = mapped_column(
        Enum(ReminderStatus), default=ReminderStatus.PENDING
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(String(1000))

    task: Mapped[Task] = relationship(back_populates="reminders")
    __table_args__ = (
        UniqueConstraint(
            "task_id", "minutes_before", "occurrence_at", name="uq_reminder_occurrence"
        ),
    )


class TaskOccurrence(Base):
    __tablename__ = "task_occurrences"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), index=True)
    occurrence_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[TaskStatus] = mapped_column(Enum(TaskStatus), default=TaskStatus.PENDING)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (UniqueConstraint("task_id", "occurrence_at", name="uq_task_occurrence"),)


class InboundEmail(Base):
    __tablename__ = "inbound_emails"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    gmail_message_id: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    gmail_history_id: Mapped[str | None] = mapped_column(String(255))
    sender: Mapped[str] = mapped_column(String(320), index=True)
    subject: Mapped[str | None] = mapped_column(String(1000))
    excerpt: Mapped[str | None] = mapped_column(String(1000))
    ics_uid: Mapped[str | None] = mapped_column(String(500), unique=True)
    extracted: Mapped[dict | None] = mapped_column(JSON)
    status: Mapped[EmailStatus] = mapped_column(Enum(EmailStatus))
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ConversationState(Base):
    __tablename__ = "conversation_states"

    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    state: Mapped[str] = mapped_column(String(50))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class WebhookEvent(Base):
    __tablename__ = "webhook_events"

    provider: Mapped[str] = mapped_column(String(30), primary_key=True)
    event_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class GmailWatchState(Base):
    __tablename__ = "gmail_watch_states"

    email_address: Mapped[str] = mapped_column(String(320), primary_key=True)
    history_id: Mapped[str] = mapped_column(String(255))
    expiration_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
