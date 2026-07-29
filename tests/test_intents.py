from app.services.intents import RuleIntentParser


def test_rule_parser_create_ru():
    intent = RuleIntentParser().parse("добавь отчет в пятницу в 15:00", "ru", "Asia/Almaty")
    assert intent.action == "create"
    assert intent.title == "отчет"
    assert "пятницу" in intent.when_text


def test_rule_parser_summary_en():
    intent = RuleIntentParser().parse("weekly summary", "en", "UTC")
    assert intent.action == "summary"
    assert intent.period == "week"


def test_rule_parser_keeps_full_russian_datetime():
    intent = RuleIntentParser().parse(
        "Добавь задачу позвонить врачу завтра в 15.00", "ru", "Asia/Almaty"
    )
    assert intent.title == "позвонить врачу"
    assert intent.when_text == "завтра в 15.00"


def test_rule_parser_relative_date_before_title():
    intent = RuleIntentParser().parse(
        "Добавь задачу завтра позвонить в акимат", "ru", "Asia/Almaty"
    )
    assert intent.title == "позвонить в акимат"
    assert intent.when_text == "завтра"


def test_rule_parser_time_before_title():
    intent = RuleIntentParser().parse("Напомни мне в 13.15 позвонить Кале", "ru", "Asia/Almaty")
    assert intent.title == "позвонить Кале"
    assert intent.when_text == "в 13.15"


def test_rule_parser_relative_reschedule():
    intent = RuleIntentParser().parse(
        "Перенеси задачу позвонить Кале на час позже", "ru", "Asia/Almaty"
    )
    assert intent.action == "reschedule"
    assert intent.task_ref == "позвонить Кале"
    assert intent.when_text == "час позже"
