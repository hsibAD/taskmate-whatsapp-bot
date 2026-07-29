from datetime import UTC, datetime

from icalendar import Calendar, Event

from app.integrations.email_parser import parse_ics


def test_ics_is_primary_structured_source():
    cal = Calendar()
    event = Event()
    event.add("uid", "event-123")
    event.add("summary", "Design review")
    event.add("dtstart", datetime(2026, 8, 1, 10, tzinfo=UTC))
    event.add("dtend", datetime(2026, 8, 1, 11, tzinfo=UTC))
    event.add("location", "Meet")
    cal.add_component(event)
    parsed = parse_ics(cal.to_ical(), "UTC")
    assert parsed.ics_uid == "event-123"
    assert parsed.title == "Design review"
    assert parsed.start_at == datetime(2026, 8, 1, 10, tzinfo=UTC)
