from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.models import Priority


class RecurrenceSpec(BaseModel):
    frequency: Literal["daily", "weekdays", "weekly", "monthly", "interval"]
    interval: int = Field(default=1, ge=1, le=365)


class Intent(BaseModel):
    action: Literal[
        "create", "list", "complete", "delete", "reschedule", "set_priority", "summary", "help"
    ]
    title: str | None = None
    task_ref: str | None = None
    when_text: str | None = None
    no_due: bool = False
    period: Literal["day", "week", "month"] | None = None
    priority: Priority = Priority.NORMAL
    reminders: list[int] | None = None
    recurrence: RecurrenceSpec | None = None

    @field_validator("reminders")
    @classmethod
    def valid_reminders(cls, value: list[int] | None) -> list[int] | None:
        if value is not None and any(minutes < 0 or minutes > 525_600 for minutes in value):
            raise ValueError("reminder must be between 0 and 525600 minutes")
        return sorted(set(value), reverse=True) if value is not None else None


class ParsedEvent(BaseModel):
    title: str
    start_at: datetime | None = None
    end_at: datetime | None = None
    timezone: str | None = None
    organizer: str | None = None
    location: str | None = None
    ics_uid: str | None = None
    confidence: float = Field(default=1, ge=0, le=1)
