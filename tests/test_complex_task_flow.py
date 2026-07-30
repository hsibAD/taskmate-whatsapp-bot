from sqlalchemy import select

from app.config import Settings
from app.models import Language, Priority, Task, User
from app.services.bot import BotService
from app.services.intents import RuleIntentParser


def test_complex_task_is_created_in_one_message(db):
    user = User(
        whatsapp_id="77001112233",
        language=Language.RU,
        timezone="Asia/Almaty",
        onboarding_step="complete",
    )
    db.add(user)
    db.commit()
    bot = BotService(Settings(_env_file=None), RuleIntentParser())

    reply = bot.handle(
        db,
        user.whatsapp_id,
        "Добавь завтра встреча с администратором в час дня напомни за 4 часа это важно",
    )

    task = db.scalar(select(Task).where(Task.user_id == user.id))
    assert task.title == "встреча с администратором"
    assert task.priority == Priority.HIGH
    assert task.due_at is not None
    assert {reminder.minutes_before for reminder in task.reminders} == {240, 0}
    assert "🔴 высокий" in reply
    assert "за 4 часа и в момент задачи" in reply
