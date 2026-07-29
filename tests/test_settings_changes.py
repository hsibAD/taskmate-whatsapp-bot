import re
from datetime import UTC, datetime

from sqlalchemy import select

from app.config import Settings
from app.models import Language, Task, User, UserEmail
from app.services.bot import BotService
from app.services.intents import RuleIntentParser


def make_bot_user(db):
    user = User(
        whatsapp_id="77009990000",
        language=Language.RU,
        timezone="Asia/Almaty",
        onboarding_step="complete",
    )
    db.add(user)
    db.flush()
    return user


def test_timezone_change_does_not_change_existing_task(db):
    user = make_bot_user(db)
    due_at = datetime(2026, 8, 1, 10, tzinfo=UTC)
    task = Task(
        user=user,
        title="Старая задача",
        due_at=due_at,
        timezone="Asia/Almaty",
    )
    db.add(task)
    db.commit()
    bot = BotService(Settings(environment="development"), RuleIntentParser())

    reply = bot.handle(db, user.whatsapp_id, "смени часовой пояс на Europe/Paris")

    assert user.timezone == "Europe/Paris"
    assert task.due_at == due_at
    assert task.timezone == "Asia/Almaty"
    assert "Старые задачи сохранили" in reply


def test_timezone_can_be_changed_using_russian_city_name(db):
    user = make_bot_user(db)
    bot = BotService(Settings(environment="development"), RuleIntentParser())

    reply = bot.handle(db, user.whatsapp_id, "Смени часовой пояс на Париж")

    assert user.timezone == "Europe/Paris"
    assert "Asia/Almaty → Europe/Paris" in reply


def test_full_timezone_command_works_while_bot_is_waiting_for_city(db):
    user = make_bot_user(db)
    bot = BotService(Settings(environment="development"), RuleIntentParser())
    first_reply = bot.handle(db, user.whatsapp_id, "Смени часовой пояс")
    assert "Укажите новый часовой пояс" in first_reply

    reply = bot.handle(db, user.whatsapp_id, "Смени часовой пояс на Париж")

    assert user.timezone == "Europe/Paris"
    assert "Asia/Almaty → Europe/Paris" in reply


def test_email_is_replaced_only_after_otp_confirmation(db):
    user = make_bot_user(db)
    old_email = UserEmail(user=user, email="old@example.com", verified=True)
    db.add(old_email)
    db.commit()
    bot = BotService(Settings(environment="development"), RuleIntentParser())

    reply = bot.handle(db, user.whatsapp_id, "замени почту на new@example.com")
    code = re.search(r"DEV-CODE: (\d{6})", reply).group(1)
    assert db.scalar(select(UserEmail).where(UserEmail.email == "old@example.com"))

    confirmation = bot.handle(db, user.whatsapp_id, code)

    emails = list(db.scalars(select(UserEmail).where(UserEmail.user_id == user.id)).all())
    assert [(item.email, item.verified) for item in emails] == [("new@example.com", True)]
    assert "Почта заменена" in confirmation
