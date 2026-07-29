import re
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import dateparser


class TimeParseError(ValueError):
    pass


TIME_PATTERN = re.compile(
    r"(?:\b(?:в|at)\s*)?(?:[01]?\d|2[0-3])(?:[.:][0-5]\d)?"
    r"(?:\s*(?:час(?:а|ов)?|am|pm|утра|дня|вечера|ночи))?",
    re.IGNORECASE,
)


def has_explicit_time(text: str) -> bool:
    lowered = text.casefold()
    if re.search(r"\b(?:полдень|полночь|noon|midnight)\b", lowered):
        return True
    return bool(
        re.search(
            r"(?:\bв\s+|\bat\s+)(?:[01]?\d|2[0-3])(?:[.:][0-5]\d)?"
            r"(?:\s*(?:час(?:а|ов)?|am|pm|утра|дня|вечера|ночи))?",
            lowered,
        )
        or re.search(r"\b(?:[01]?\d|2[0-3])[.:][0-5]\d\b", lowered)
        or re.search(r"\b\d{1,2}\s*(?:am|pm|утра|дня|вечера|ночи)\b", lowered)
    )


def normalize_time_phrases(text: str) -> str:
    value = text.casefold()
    value = re.sub(r"\b(\d{1,2})\s*час(?:а|ов)?\s*дня\b", r"\1 pm", value)
    value = re.sub(r"\b(\d{1,2})\s*час(?:а|ов)?\s*вечера\b", r"\1 pm", value)
    value = re.sub(r"\b(\d{1,2})\s*час(?:а|ов)?\s*утра\b", r"\1 am", value)
    value = re.sub(r"\b(\d{1,2})\s*час(?:а|ов)?\s*ночи\b", r"\1 am", value)
    value = re.sub(r"\b([01]?\d|2[0-3])\.([0-5]\d)\b", r"\1:\2", value)
    return value


def as_utc(value: datetime) -> datetime:
    """Normalize DB/adapter timestamps; SQLite may drop timezone metadata."""
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def validate_timezone(name: str) -> str:
    aliases = {
        "алматы": "Asia/Almaty",
        "almaty": "Asia/Almaty",
        "астана": "Asia/Almaty",
        "astana": "Asia/Almaty",
        "париж": "Europe/Paris",
        "paris": "Europe/Paris",
        "лондон": "Europe/London",
        "london": "Europe/London",
        "москва": "Europe/Moscow",
        "moscow": "Europe/Moscow",
        "берлин": "Europe/Berlin",
        "berlin": "Europe/Berlin",
        "рим": "Europe/Rome",
        "rome": "Europe/Rome",
        "токио": "Asia/Tokyo",
        "tokyo": "Asia/Tokyo",
        "дубай": "Asia/Dubai",
        "dubai": "Asia/Dubai",
        "стамбул": "Europe/Istanbul",
        "istanbul": "Europe/Istanbul",
        "тбилиси": "Asia/Tbilisi",
        "tbilisi": "Asia/Tbilisi",
        "бангкок": "Asia/Bangkok",
        "bangkok": "Asia/Bangkok",
        "нью-йорк": "America/New_York",
        "нью йорк": "America/New_York",
        "new york": "America/New_York",
        "лос-анджелес": "America/Los_Angeles",
        "лос анджелес": "America/Los_Angeles",
        "los angeles": "America/Los_Angeles",
    }
    name = aliases.get(name.strip().casefold(), name.strip())
    try:
        ZoneInfo(name)
    except ZoneInfoNotFoundError as exc:
        raise TimeParseError(f"Unknown timezone: {name}") from exc
    return name


def parse_future_datetime(
    text: str, timezone: str, *, now: datetime | None = None, language: str | None = None
) -> datetime:
    zone = ZoneInfo(validate_timezone(timezone))
    reference = (now or datetime.now(UTC)).astimezone(zone)
    normalized = normalize_time_phrases(text)
    time_only_match = re.fullmatch(
        r"\s*(?:в|at)\s+([01]?\d|2[0-3])(?::([0-5]\d))?\s*(am|pm)?\s*",
        normalized,
        re.IGNORECASE,
    )
    if time_only_match:
        hour = int(time_only_match.group(1))
        minute = int(time_only_match.group(2) or 0)
        marker = (time_only_match.group(3) or "").casefold()
        if marker == "pm" and hour < 12:
            hour += 12
        if marker == "am" and hour == 12:
            hour = 0
        candidate = reference.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if candidate <= reference:
            raise TimeParseError("Time has passed today; specify a day")
        return candidate.astimezone(UTC)
    weekday_match = re.search(
        r"\b(?:(?:в\s+)?(?:следующ(?:ий|ую|ее)|next)\s+)?"
        r"(понедельник|вторник|среду|четверг|пятницу|субботу|воскресенье|"
        r"monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
        normalized,
        re.IGNORECASE,
    )
    if weekday_match:
        weekdays = {
            "понедельник": 0,
            "monday": 0,
            "вторник": 1,
            "tuesday": 1,
            "среду": 2,
            "wednesday": 2,
            "четверг": 3,
            "thursday": 3,
            "пятницу": 4,
            "friday": 4,
            "субботу": 5,
            "saturday": 5,
            "воскресенье": 6,
            "sunday": 6,
        }
        target_weekday = weekdays[weekday_match.group(1).casefold()]
        days_ahead = (target_weekday - reference.weekday()) % 7 or 7
        target_date = (reference + timedelta(days=days_ahead)).date()
        time_match = re.search(
            r"\b([01]?\d|2[0-3])(?::([0-5]\d))?\s*(am|pm)?\b",
            normalized[weekday_match.end() :],
            re.IGNORECASE,
        )
        if time_match:
            hour = int(time_match.group(1))
            minute = int(time_match.group(2) or 0)
            marker = (time_match.group(3) or "").casefold()
            if marker == "pm" and hour < 12:
                hour += 12
            if marker == "am" and hour == 12:
                hour = 0
        else:
            hour, minute = reference.hour, reference.minute
        parsed_weekday = datetime.combine(target_date, datetime.min.time(), zone).replace(
            hour=hour, minute=minute
        )
        return parsed_weekday.astimezone(UTC)
    parsed = dateparser.parse(
        normalized,
        languages=[language] if language in {"ru", "en"} else None,
        settings={
            "TIMEZONE": timezone,
            "TO_TIMEZONE": "UTC",
            "RETURN_AS_TIMEZONE_AWARE": True,
            "RELATIVE_BASE": reference,
            "PREFER_DATES_FROM": "future",
        },
    )
    if parsed is None:
        raise TimeParseError("I could not understand the date and time")
    utc_value = parsed.astimezone(UTC)
    if utc_value <= (now or datetime.now(UTC)):
        raise TimeParseError("Date and time must be in the future")
    return utc_value


def period_bounds(
    period: str, timezone: str, now: datetime | None = None
) -> tuple[datetime, datetime]:
    zone = ZoneInfo(validate_timezone(timezone))
    local_now = (now or datetime.now(UTC)).astimezone(zone)
    day_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    if period == "day":
        start, end = day_start, day_start + timedelta(days=1)
    elif period == "week":
        start = day_start - timedelta(days=day_start.weekday())
        end = start + timedelta(days=7)
    elif period == "month":
        start = day_start.replace(day=1)
        end = (
            start.replace(year=start.year + 1, month=1)
            if start.month == 12
            else start.replace(month=start.month + 1)
        )
    else:
        raise TimeParseError(f"Unsupported period: {period}")
    return start.astimezone(UTC), end.astimezone(UTC)


def format_local(value: datetime | None, timezone: str, language: str) -> str:
    if value is None:
        return "без срока" if language == "ru" else "no due date"
    return as_utc(value).astimezone(ZoneInfo(timezone)).strftime("%d.%m.%Y %H:%M")
