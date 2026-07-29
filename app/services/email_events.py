import json
from datetime import UTC, datetime

from openai import OpenAI
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.integrations.email_parser import (
    extract_ics,
    extract_text,
    gmail_headers,
    gmail_received_at,
    normalize_email,
    parse_event_text_rules,
    parse_ics,
)
from app.models import (
    ConversationState,
    EmailStatus,
    InboundEmail,
    Task,
    TaskKind,
    User,
    UserEmail,
)
from app.schemas import ParsedEvent
from app.services.tasks import schedule_reminders
from app.services.time import format_local


def parse_event_text(text: str, subject: str, timezone: str, settings: Settings) -> ParsedEvent:
    if not settings.openai_api_key.get_secret_value():
        raise ValueError("LLM is not configured")
    response = OpenAI(api_key=settings.openai_api_key.get_secret_value()).responses.create(
        model=settings.openai_model,
        instructions=(
            "Extract an invitation or event from this email. Resolve relative dates using the "
            f"recipient timezone {timezone}. Return null start_at when date or time is ambiguous. "
            "Never invent a missing event."
        ),
        input=f"Subject: {subject}\n\n{text[:12000]}",
        text={
            "format": {
                "type": "json_schema",
                "name": "email_event",
                "strict": True,
                "schema": ParsedEvent.model_json_schema(),
            }
        },
    )
    return ParsedEvent.model_validate(json.loads(response.output_text))


def ingest_gmail_message(
    db: Session, message: dict, settings: Settings
) -> tuple[InboundEmail, str | None, str | None]:
    message_id = message["id"]
    existing = db.scalar(select(InboundEmail).where(InboundEmail.gmail_message_id == message_id))
    if existing:
        return existing, None, None
    headers = gmail_headers(message)
    sender = normalize_email(headers.get("from", ""))
    link = db.scalar(
        select(UserEmail).where(UserEmail.email == sender, UserEmail.verified.is_(True))
    )
    record = InboundEmail(
        gmail_message_id=message_id,
        gmail_history_id=message.get("historyId"),
        sender=sender,
        subject=headers.get("subject"),
        excerpt=message.get("snippet", "")[: settings.email_excerpt_max_chars],
        received_at=gmail_received_at(message),
        status=EmailStatus.UNLINKED,
    )
    db.add(record)
    db.flush()
    if not link:
        return record, None, None
    record.user_id = link.user_id
    user = link.user
    ics = extract_ics(message.get("payload", {}))
    if not ics:
        text = extract_text(message.get("payload", {}))
        event = parse_event_text_rules(
            f"{record.subject or ''}\n{text}", record.subject or "", user.timezone
        )
        try:
            event = event or parse_event_text(text, record.subject or "", user.timezone, settings)
        except Exception:
            pass
        if event and event.start_at:
            return stage_email_event(db, record, user, event)
        record.status = EmailStatus.NEEDS_DETAILS
        record.extracted = {
            "title": (
                (record.subject or "Событие из письма")
                .removeprefix("Fwd:")
                .removeprefix("FW:")
                .strip()
            )
            or "Событие из письма"
        }
        db.merge(
            ConversationState(
                user_id=user.id,
                state="email_event_details",
                payload={"email_id": record.id},
            )
        )
        return (
            record,
            user.whatsapp_id,
            (
                f"Письмо «{record.subject or 'Без темы'}» получено, но точные дата и время "
                "не найдены. Напишите их здесь, например: «завтра в 15:00»."
                if user.language.value == "ru"
                else f"Email “{record.subject or 'No subject'}” was received, but no date and "
                "time were found. Send them here, for example: “tomorrow at 3 pm”."
            ),
        )
    try:
        event = parse_ics(ics, user.timezone)
    except Exception as exc:
        record.status = EmailStatus.FAILED
        record.extracted = {"error": str(exc)[:500]}
        return (
            record,
            user.whatsapp_id,
            (
                "Не удалось прочитать календарное приглашение."
                if user.language.value == "ru"
                else "Could not read the calendar invitation."
            ),
        )
    return stage_email_event(db, record, user, event)


def stage_email_event(db: Session, record: InboundEmail, user: User, event: ParsedEvent):
    duplicate = (
        db.scalar(select(InboundEmail).where(InboundEmail.ics_uid == event.ics_uid))
        if event.ics_uid
        else None
    )
    if duplicate and duplicate.id != record.id:
        record.status = EmailStatus.REJECTED
        record.extracted = {"duplicate_of": duplicate.id}
        return record, None, None
    record.ics_uid = event.ics_uid
    record.extracted = event.model_dump(mode="json")
    record.status = EmailStatus.AWAITING_CONFIRMATION
    db.merge(
        ConversationState(
            user_id=user.id,
            state="email_event_confirmation",
            payload={"email_id": record.id},
        )
    )
    when = format_local(event.start_at, user.timezone, user.language.value)
    prompt = (
        f"Новое приглашение: {event.title}\nКогда: {when}\n"
        f"Место: {event.location or '—'}\nДобавить? Ответьте ДА или НЕТ."
        if user.language.value == "ru"
        else f"New invitation: {event.title}\nWhen: {when}\n"
        f"Location: {event.location or '—'}\nAdd it? Reply YES or NO."
    )
    return record, user.whatsapp_id, prompt


def confirm_email_event(
    db: Session, state: ConversationState, accepted: bool
) -> tuple[Task | None, str]:
    record = db.get(InboundEmail, state.payload["email_id"])
    user = record and db.get(User, record.user_id)
    if not record or not user or record.status != EmailStatus.AWAITING_CONFIRMATION:
        db.delete(state)
        return None, "Invitation expired."
    if not accepted:
        record.status = EmailStatus.REJECTED
        db.delete(state)
        return None, "Отклонено." if user.language.value == "ru" else "Rejected."
    event = ParsedEvent.model_validate(record.extracted)
    task = Task(
        user_id=user.id,
        kind=TaskKind.EVENT,
        title=event.title,
        due_at=event.start_at,
        end_at=event.end_at,
        timezone=user.timezone,
        location=event.location,
        organizer=event.organizer,
        source_email_id=record.id,
    )
    db.add(task)
    db.flush()
    schedule_reminders(db, task, user.default_reminders, now=datetime.now(UTC))
    record.status = EmailStatus.CONFIRMED
    state.state = "email_event_reminders"
    state.payload = {"task_id": task.id}
    return task, (
        "Событие добавлено. За сколько предупредить? Например: «за день и за час», "
        "«за 30 минут», «в момент события» или «по умолчанию»."
        if user.language.value == "ru"
        else "Event added. When should I remind you? For example: “one day and one hour”, "
        "“30 minutes”, “at the event time”, or “default”."
    )
