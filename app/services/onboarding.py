import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from email_validator import validate_email
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import Language, User, UserEmail
from app.services.time import validate_timezone


def otp_hash(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()


def begin_email_verification(
    db: Session, user: User, email: str, settings: Settings
) -> tuple[UserEmail, str]:
    normalized = validate_email(email, check_deliverability=False).normalized.casefold()
    existing = db.scalar(select(UserEmail).where(UserEmail.email == normalized))
    if existing and existing.user_id != user.id:
        raise ValueError("This email is already linked")
    record = existing or UserEmail(user=user, email=normalized)
    code = f"{secrets.randbelow(1_000_000):06d}"
    record.verified = False
    record.otp_hash = otp_hash(code)
    record.otp_expires_at = datetime.now(UTC) + timedelta(minutes=settings.otp_ttl_minutes)
    db.add(record)
    return record, code


def confirm_email(record: UserEmail, code: str) -> bool:
    now = datetime.now(UTC)
    if (
        not record.otp_hash
        or not record.otp_expires_at
        or record.otp_expires_at.replace(tzinfo=UTC) < now
        or not secrets.compare_digest(record.otp_hash, otp_hash(code.strip()))
    ):
        return False
    record.verified = True
    record.otp_hash = None
    record.otp_expires_at = None
    return True


def onboarding_reply(user: User, text: str, settings: Settings) -> str | None:
    value = text.strip()
    if user.onboarding_step == "language":
        if value.casefold() not in {"ru", "русский", "en", "english"}:
            return (
                "Привет! Я TaskMate 👋\n\n"
                "Я помогу вам:\n"
                "• создавать задачи обычными сообщениями;\n"
                "• напоминать о делах заранее и точно в срок;\n"
                "• переносить, завершать и удалять задачи;\n"
                "• показывать сводки на день, неделю и месяц;\n"
                "• добавлять встречи из писем.\n\n"
                "Для начала выберите язык: RU / EN\n\n"
                "Hi! I’m TaskMate 👋\n"
                "I organize tasks, reminders, summaries, and email invitations.\n"
                "Choose your language: RU / EN"
            )
        user.language = Language.RU if value.casefold() in {"ru", "русский"} else Language.EN
        user.onboarding_step = "timezone"
        return (
            "Укажите часовой пояс, например Europe/Moscow или Asia/Almaty."
            if user.language == Language.RU
            else "Enter your timezone, for example Europe/London or Asia/Almaty."
        )
    if user.onboarding_step == "timezone":
        try:
            user.timezone = validate_timezone(value)
        except ValueError:
            return (
                "Неизвестный часовой пояс. Используйте формат Europe/Moscow."
                if user.language == Language.RU
                else "Unknown timezone. Use a name such as Europe/London."
            )
        user.default_reminders = settings.default_reminders
        user.onboarding_step = "complete"
        return (
            "Всё готово! 🎉\n\n"
            "Что я умею:\n"
            "• создавать задачи обычными сообщениями;\n"
            "• уточнять недостающие дату, время и напоминания;\n"
            "• переносить, завершать и удалять задачи;\n"
            "• показывать сводки на день, неделю и месяц;\n"
            "• принимать приглашения и задачи из писем.\n\n"
            "Пример задачи:\n"
            "«Напомни завтра в 15:00 позвонить врачу».\n\n"
            f"Письма отправляйте на адрес бота: {settings.gmail_bot_address or 'почта бота'}.\n"
            "Отправлять их нужно с вашей подтверждённой почты. В теме можно сразу написать, "
            "например: «Встреча с клиентом 3 августа в 15:00». Можно также переслать обычное "
            "приглашение — файл ICS необязателен. Если данных не хватит, я уточню их здесь, "
            "в WhatsApp.\n\n"
            "Чтобы зарегистрировать свою почту, напишите:\n"
            "«Моя почта: name@example.com».\n\n"
            "Напишите «что ты умеешь», чтобы открыть меню с кнопками."
            if user.language == Language.RU
            else "All set! 🎉\n\nI can create, reschedule, complete, and delete tasks; "
            "send reminders; show daily, weekly, and monthly summaries; and process tasks "
            "or invitations from emails.\n\n"
            "Example: “Remind me to call the doctor tomorrow at 3 pm”.\n\n"
            f"Send emails to: {settings.gmail_bot_address or 'the bot email address'}. "
            "They must come from your verified email. You can put the task and time directly "
            "in the subject, for example: “Client meeting August 3 at 3 pm”. ICS is optional; "
            "if details are missing, I will ask in WhatsApp.\n\n"
            "To register your email, send: “My email: name@example.com”.\n\n"
            "Send “what can you do” to open the button menu."
        )
    return None
