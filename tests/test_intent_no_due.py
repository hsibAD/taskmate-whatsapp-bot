from app.services.intents import RuleIntentParser


def test_create_task_without_due_date():
    intent = RuleIntentParser().parse("добавь купить батарейки без срока", "ru", "Asia/Almaty")
    assert intent.action == "create"
    assert intent.title == "купить батарейки"
    assert intent.no_due is True
    assert intent.when_text is None
