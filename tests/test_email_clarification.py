import base64

from app.config import Settings
from app.models import EmailStatus, Language, User, UserEmail
from app.services.bot import BotService
from app.services.email_events import ingest_gmail_message
from app.services.intents import RuleIntentParser


def gmail_text_message(message_id: str, sender: str, subject: str, body: str) -> dict:
    encoded = base64.urlsafe_b64encode(body.encode()).decode().rstrip("=")
    return {
        "id": message_id,
        "historyId": "100",
        "snippet": body,
        "payload": {
            "headers": [
                {"name": "From", "value": sender},
                {"name": "Subject", "value": subject},
            ],
            "mimeType": "text/plain",
            "body": {"data": encoded},
        },
    }


def test_missing_email_date_can_be_clarified_in_whatsapp(db):
    user = User(
        whatsapp_id="77007770000",
        language=Language.RU,
        timezone="Asia/Almaty",
        onboarding_step="complete",
    )
    db.add(user)
    db.flush()
    db.add(UserEmail(user=user, email="user@example.com", verified=True))
    db.commit()
    settings = Settings(environment="development", openai_api_key="")
    message = gmail_text_message(
        "mail-without-date",
        "user@example.com",
        "Fwd: Встреча с клиентом",
        "Предлагаю встретиться и обсудить проект.",
    )

    record, recipient, prompt = ingest_gmail_message(db, message, settings)
    db.commit()

    assert record.status == EmailStatus.NEEDS_DETAILS
    assert recipient == user.whatsapp_id
    assert "Напишите их здесь" in prompt

    bot = BotService(settings, RuleIntentParser())
    reply = bot.handle(db, user.whatsapp_id, "3 августа 2099 в 15:00")

    assert "Новое приглашение: Встреча с клиентом" in reply
    assert "Добавить? Ответьте ДА или НЕТ." in reply
    assert record.status == EmailStatus.AWAITING_CONFIRMATION


def test_email_subject_date_is_parsed_without_ics(db):
    user = User(
        whatsapp_id="77007770001",
        language=Language.RU,
        timezone="Asia/Almaty",
        onboarding_step="complete",
    )
    db.add(user)
    db.flush()
    db.add(UserEmail(user=user, email="subject@example.com", verified=True))
    db.commit()
    settings = Settings(environment="development", openai_api_key="")
    message = gmail_text_message(
        "mail-subject-date",
        "subject@example.com",
        "Fwd: Встреча 3 августа 2099 в 15:00",
        "Приглашаю вас на встречу.",
    )

    record, _, prompt = ingest_gmail_message(db, message, settings)

    assert record.status == EmailStatus.AWAITING_CONFIRMATION
    assert "Когда: 03.08.2099 15:00" in prompt
