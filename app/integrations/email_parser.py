import base64
import html
import re
from datetime import UTC, date, datetime
from email.utils import parseaddr, parsedate_to_datetime
from zoneinfo import ZoneInfo

import dateparser
from icalendar import Calendar

from app.schemas import ParsedEvent


def normalize_email(value: str) -> str:
    return parseaddr(value)[1].strip().casefold()


def decode_body(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def _walk_parts(part: dict) -> list[dict]:
    result = [part]
    for child in part.get("parts", []):
        result.extend(_walk_parts(child))
    return result


def extract_ics(payload: dict) -> bytes | None:
    for part in _walk_parts(payload):
        if part.get("mimeType") == "text/calendar":
            data = part.get("body", {}).get("data")
            if data:
                return decode_body(data)
    return None


def extract_text(payload: dict) -> str:
    html_fallback = ""
    for part in _walk_parts(payload):
        mime = part.get("mimeType")
        data = part.get("body", {}).get("data")
        if not data:
            continue
        decoded = decode_body(data).decode("utf-8", errors="replace")
        if mime == "text/plain":
            return decoded
        if mime == "text/html":
            html_fallback = decoded
    if html_fallback:
        return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html.unescape(html_fallback)))
    return ""


def parse_event_text_rules(text: str, subject: str, fallback_timezone: str) -> ParsedEvent | None:
    """Extract common RU/EN invitation formats with deterministic rules."""
    clean = html.unescape(text).replace("\u202f", " ").replace("\xa0", " ")
    date_value = None
    time_value = None
    date_patterns = (
        r"(?:^|\n)\s*>?\s*(?:дата|date)\s*:\s*([^\n]+)",
        (
            r"\b(\d{1,2}\s+(?:января|февраля|марта|апреля|мая|июня|июля|августа|"
            r"сентября|октября|ноября|декабря)\s+\d{4}(?:\s+года?)?)"
        ),
        r"\b(\d{1,2}[./-]\d{1,2}[./-]\d{2,4})\b",
    )
    for pattern in date_patterns:
        matches = re.findall(pattern, clean, re.IGNORECASE | re.MULTILINE)
        if matches:
            # Forwarded headers usually occur first; the invitation date is normally last.
            date_value = matches[-1].strip()
            break
    time_matches = re.findall(
        r"(?:^|\n)\s*>?\s*(?:время|time)\s*:\s*([0-2]?\d[.:][0-5]\d)"
        r"|\b(?:в|at)\s+([0-2]?\d[.:][0-5]\d)\b",
        clean,
        re.IGNORECASE | re.MULTILINE,
    )
    if time_matches:
        pair = time_matches[-1]
        time_value = next(value for value in pair if value).replace(".", ":")
    if not date_value or not time_value:
        return None
    start = dateparser.parse(
        f"{date_value} {time_value}",
        languages=["ru", "en"],
        settings={
            "TIMEZONE": fallback_timezone,
            "RETURN_AS_TIMEZONE_AWARE": True,
            "DATE_ORDER": "DMY",
        },
    )
    if not start:
        return None
    title_match = re.search(
        r"(?:приглаша(?:ем|ю)\s+вас\s+(?:посетить|на)|"
        r"you are invited to|invitation to)\s+([^,\n.]+)",
        clean,
        re.IGNORECASE,
    )
    title = title_match.group(1).strip() if title_match else re.sub(
        r"^(?:fwd|fw|re)\s*:\s*", "", subject, flags=re.IGNORECASE
    ).strip()
    if not title or title.casefold() in {"пригласительное", "приглашение", "invitation"}:
        title = "Событие из письма"
    return ParsedEvent(
        title=title[:500],
        start_at=start.astimezone(UTC),
        timezone=fallback_timezone,
        confidence=0.85,
    )


def parse_ics(data: bytes, fallback_timezone: str) -> ParsedEvent:
    calendar = Calendar.from_ical(data)
    event = next((item for item in calendar.walk() if item.name == "VEVENT"), None)
    if event is None:
        raise ValueError("No VEVENT in calendar attachment")
    start = event.decoded("dtstart")
    end = event.decoded("dtend", None)
    if isinstance(start, date) and not isinstance(start, datetime):
        start = datetime.combine(start, datetime.min.time(), ZoneInfo(fallback_timezone))
    if isinstance(end, date) and not isinstance(end, datetime):
        end = datetime.combine(end, datetime.min.time(), ZoneInfo(fallback_timezone))
    if start.tzinfo is None:
        start = start.replace(tzinfo=ZoneInfo(fallback_timezone))
    if end and end.tzinfo is None:
        end = end.replace(tzinfo=ZoneInfo(fallback_timezone))
    organizer = str(event.get("organizer", "")).removeprefix("mailto:") or None
    return ParsedEvent(
        title=str(event.get("summary", "Calendar event")),
        start_at=start.astimezone(UTC),
        end_at=end.astimezone(UTC) if end else None,
        timezone=getattr(start.tzinfo, "key", fallback_timezone),
        organizer=organizer,
        location=str(event.get("location", "")) or None,
        ics_uid=str(event.get("uid", "")) or None,
    )


def gmail_headers(message: dict) -> dict[str, str]:
    return {
        item["name"].casefold(): item["value"]
        for item in message.get("payload", {}).get("headers", [])
    }


def gmail_received_at(message: dict) -> datetime | None:
    headers = gmail_headers(message)
    try:
        return parsedate_to_datetime(headers["date"]).astimezone(UTC)
    except (KeyError, TypeError, ValueError):
        return None
