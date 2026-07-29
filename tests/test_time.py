from datetime import UTC, datetime

import pytest

from app.services.time import TimeParseError, parse_future_datetime, period_bounds


def test_parses_russian_relative_time():
    now = datetime(2026, 7, 28, 12, tzinfo=UTC)
    result = parse_future_datetime("завтра в 15:00", "Asia/Almaty", now=now, language="ru")
    assert result == datetime(2026, 7, 29, 10, tzinfo=UTC)


def test_rejects_past_time():
    now = datetime(2026, 7, 28, 12, tzinfo=UTC)
    with pytest.raises(TimeParseError):
        parse_future_datetime("2020-01-01 10:00", "UTC", now=now, language="en")


def test_month_bounds_are_calendar_month():
    now = datetime(2026, 7, 28, 12, tzinfo=UTC)
    start, end = period_bounds("month", "UTC", now)
    assert start == datetime(2026, 7, 1, tzinfo=UTC)
    assert end == datetime(2026, 8, 1, tzinfo=UTC)


def test_next_monday_three_in_afternoon():
    now = datetime(2026, 7, 29, 7, tzinfo=UTC)
    result = parse_future_datetime(
        "в следующий понедельник в 3 часа дня",
        "Asia/Almaty",
        now=now,
        language="ru",
    )
    assert result == datetime(2026, 8, 3, 10, tzinfo=UTC)
