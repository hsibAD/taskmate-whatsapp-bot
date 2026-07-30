import re


def parse_reminder_minutes(text: str) -> list[int] | None:
    lowered = text.casefold().strip()
    lowered = re.sub(r"\bпол\s+часа\b", "полчаса", lowered)
    if lowered in {"по умолчанию", "default", "ок", "ok"}:
        return None
    if lowered in {
        "в момент события",
        "в момент задачи",
        "точно в срок",
        "только в момент события",
        "только в момент задачи",
        "at the event time",
        "at due time",
    }:
        return [0]
    units = {
        "минут": 1,
        "минуты": 1,
        "минуту": 1,
        "minute": 1,
        "minutes": 1,
        "час": 60,
        "часа": 60,
        "часов": 60,
        "hour": 60,
        "hours": 60,
        "день": 1440,
        "дня": 1440,
        "дней": 1440,
        "day": 1440,
        "days": 1440,
    }
    word_numbers = {
        "полчаса": 30,
        "час": 60,
        "день": 1440,
        "one hour": 60,
        "one day": 1440,
    }
    values: list[int] = []
    fractional_patterns = {
        r"\bполтора\s+часа\b": 90,
        r"\bчас\s+с\s+половиной\b": 90,
        r"\bполтора\s+дня\b": 2160,
        r"\bone\s+and\s+a\s+half\s+hours?\b": 90,
        r"\ban\s+hour\s+and\s+a\s+half\b": 90,
    }
    for pattern, minutes in fractional_patterns.items():
        if re.search(pattern, lowered):
            values.append(minutes)
            lowered = re.sub(pattern, " ", lowered)
    values.extend(
        minutes
        for phrase, minutes in word_numbers.items()
        if re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", lowered)
    )
    for number, unit in re.findall(
        r"(\d+)\s*(минут(?:у|ы)?|час(?:а|ов)?|д(?:ень|ня|ней)|minutes?|hours?|days?)",
        lowered,
    ):
        values.append(int(number) * units[unit])
    return sorted(set(values), reverse=True) if values else []
