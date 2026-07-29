from datetime import UTC, datetime

from app.config import Settings
from app.models import Language, Task, User
from app.services.bot import BotService
from app.services.intents import RuleIntentParser


def test_duplicate_task_choice_contains_dates(db):
    user = User(
        whatsapp_id="77001230000",
        language=Language.RU,
        timezone="Asia/Almaty",
        onboarding_step="complete",
    )
    db.add(user)
    db.flush()
    db.add_all(
        [
            Task(
                user=user,
                title="позвонить врачу",
                due_at=datetime(2026, 7, 30, 5, tzinfo=UTC),
                timezone="Asia/Almaty",
            ),
            Task(
                user=user,
                title="позвонить врачу",
                due_at=datetime(2026, 8, 3, 10, tzinfo=UTC),
                timezone="Europe/Paris",
            ),
        ]
    )
    db.commit()
    bot = BotService(Settings(environment="development"), RuleIntentParser())

    reply = bot.handle(db, user.whatsapp_id, "Выполнила позвонить врачу")

    assert reply == (
        "Выберите задачу:\n"
        "1. позвонить врачу — 30.07.2026 10:00\n"
        "2. позвонить врачу — 03.08.2026 12:00"
    )
