from app.config import Settings
from app.models import Language, User, UserEmail
from app.services.bot import BotService
from app.services.intents import RuleIntentParser


def test_capabilities_phrase_opens_menu(db):
    user = User(
        whatsapp_id="77005550000",
        language=Language.RU,
        timezone="Asia/Almaty",
        onboarding_step="complete",
    )
    db.add(user)
    db.commit()
    bot = BotService(Settings(environment="development"), RuleIntentParser())

    reply = bot.handle(db, user.whatsapp_id, "Какие у тебя возможности")

    assert reply == BotService.HELP_MENU_RU


def test_add_task_button_starts_friendly_flow(db):
    user = User(
        whatsapp_id="77005550001",
        language=Language.RU,
        timezone="Asia/Almaty",
        onboarding_step="complete",
    )
    db.add(user)
    db.commit()
    bot = BotService(Settings(environment="development"), RuleIntentParser())

    first = bot.handle(db, user.whatsapp_id, "__menu_add_task__")
    second = bot.handle(db, user.whatsapp_id, "позвонить врачу")

    assert "Что нужно сделать?" in first
    assert second == (
        "Записал: «позвонить врачу». На какой день и время поставить задачу?"
    )


def test_email_help_shows_bot_and_verified_user_addresses(db):
    user = User(
        whatsapp_id="77005550002",
        language=Language.RU,
        timezone="Asia/Almaty",
        onboarding_step="complete",
    )
    db.add(user)
    db.flush()
    db.add(UserEmail(user=user, email="user@example.com", verified=True))
    db.commit()
    settings = Settings(
        environment="development",
        gmail_bot_address="bot@example.com",
    )
    bot = BotService(settings, RuleIntentParser())

    reply = bot.handle(db, user.whatsapp_id, "Как отправить тебе письмо?")

    assert "bot@example.com" in reply
    assert "Ваша подтверждённая почта: user@example.com" in reply
    assert "Файл ICS полезен, но необязателен" in reply


def test_email_help_offers_registration_when_email_is_missing(db):
    user = User(
        whatsapp_id="77005550003",
        language=Language.RU,
        timezone="Asia/Almaty",
        onboarding_step="complete",
    )
    db.add(user)
    db.commit()
    bot = BotService(
        Settings(environment="development", gmail_bot_address="bot@example.com"),
        RuleIntentParser(),
    )

    reply = bot.handle(db, user.whatsapp_id, "Как работает почта")

    assert "У вас пока нет подтверждённой почты" in reply
    assert "Моя почта: name@example.com" in reply
