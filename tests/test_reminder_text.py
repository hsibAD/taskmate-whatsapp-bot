from app.services.bot import BotService, parse_reminder_minutes


def test_natural_reminder_intervals():
    assert parse_reminder_minutes("за день и за час") == [1440, 60]
    assert parse_reminder_minutes("за 2 часа и за 30 минут") == [120, 30]
    assert parse_reminder_minutes("только в момент события") == [0]
    assert parse_reminder_minutes("по умолчанию") is None
    assert parse_reminder_minutes("за пол часа") == [30]
    assert parse_reminder_minutes("за полчаса") == [30]
    assert parse_reminder_minutes("за полтора часа") == [90]
    assert parse_reminder_minutes("за час с половиной") == [90]
    assert parse_reminder_minutes("за день и за полтора часа") == [1440, 90]


def test_human_readable_reminder_intervals():
    assert (
        BotService._format_reminder_intervals([1440, 60], True, False)
        == "за 1 день, за 1 час и в момент задачи"
    )
    assert (
        BotService._format_reminder_intervals([2880, 300, 30], True)
        == "за 2 дня, за 5 часов, за 30 минут и в момент события"
    )
    assert (
        BotService._format_reminder_intervals([90], True, False)
        == "за 1 час 30 минут и в момент задачи"
    )
