from datetime import UTC, datetime

from app.integrations.email_parser import parse_event_text_rules


def test_parse_forwarded_russian_invitation_without_ics():
    text = """
    > Дата: 29 июля 2026 г. в 17:44:50 GMT+5
    Приглашаем вас посетить Игры кочевников, которые состоятся 30 июля 2026 года в 10:00.
    Дата: 30 июля 2026 года
    Время: 10:00
    """
    event = parse_event_text_rules(text, "Fwd: Пригласительное", "Asia/Almaty")
    assert event is not None
    assert event.title == "Игры кочевников"
    assert event.start_at == datetime(2026, 7, 30, 5, 0, tzinfo=UTC)
