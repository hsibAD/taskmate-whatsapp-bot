import re
from abc import ABC, abstractmethod

from openai import OpenAI

from app.config import Settings
from app.models import Priority
from app.schemas import Intent
from app.services.reminders import parse_reminder_minutes


class IntentParser(ABC):
    @abstractmethod
    def parse(self, text: str, language: str, timezone: str) -> Intent: ...


class RuleIntentParser(IntentParser):
    """Safe fallback and parser for explicit bot commands."""

    def parse(self, text: str, language: str, timezone: str) -> Intent:
        raw = text.strip()
        lower = raw.casefold()
        if lower in {
            "help",
            "помощь",
            "/help",
            "команды",
            "меню",
            "возможности",
            "что ты умеешь",
            "что ты можешь",
            "что ты можешь делать",
            "какие у тебя возможности",
            "what can you do",
            "capabilities",
            "menu",
        }:
            return Intent(action="help")
        if any(token in lower for token in ("сводка", "summary", "overview")):
            period = (
                "month"
                if any(x in lower for x in ("месяц", "month"))
                else ("week" if any(x in lower for x in ("недел", "week")) else "day")
            )
            return Intent(action="summary", period=period)
        if lower in {
            "задачи",
            "мои задачи",
            "покажи задачи",
            "покажи мои задачи",
            "список",
            "список задач",
            "list",
            "tasks",
            "my tasks",
            "show my tasks",
        }:
            return Intent(action="list")

        action_patterns = [
            ("complete", r"^(?:выполнил[а]?|готово|заверши(?:ть)?|complete|done)\s+(.+)$"),
            ("delete", r"^(?:удали(?:ть)?|delete|remove)\s+(.+)$"),
            (
                "reschedule",
                (
                    r"^(?:перенеси(?:ть)?|передвинь|reschedule|move)\s+"
                    r"(?:задачу\s+|task\s+)?(.+?)\s+(?:на|to)\s+(.+)$"
                ),
            ),
        ]
        for action, pattern in action_patterns:
            match = re.match(pattern, raw, re.IGNORECASE)
            if match:
                if action == "reschedule":
                    return Intent(action=action, task_ref=match.group(1), when_text=match.group(2))
                return Intent(action=action, task_ref=match.group(1))

        create = re.match(
            r"^(?:добавь|создай|напомни|add|create|remind me(?: to)?)\s+"
            r"(?:задачу\s+|task\s+)?(.+)$",
            raw,
            re.IGNORECASE,
        )
        if create:
            body = create.group(1).strip()
            body = re.sub(r"^(?:мне|me)\s+", "", body, flags=re.IGNORECASE)
            priority = (
                Priority.LOW
                if re.search(
                    r"\b(?:неважно|низк(?:ий|ого)\s+приоритет|low\s+priority)\b",
                    body,
                    re.IGNORECASE,
                )
                else Priority.HIGH
                if re.search(
                    r"\b(?:это\s+)?(?:важно|срочно|high\s+priority|urgent)\b", body, re.IGNORECASE
                )
                else Priority.NORMAL
            )
            body = re.sub(
                r"\s*\b(?:это\s+)?(?:важно|срочно|неважно|"
                r"низк(?:ий|ого)\s+приоритет|high\s+priority|low\s+priority|urgent)\b\s*",
                " ",
                body,
                flags=re.IGNORECASE,
            ).strip()
            reminder_match = re.search(
                r"\s*\b(?:напомни|предупреди|remind)(?:\s+мне)?\s+"
                r"(.+?)(?=$|\s+\b(?:это\s+)?(?:важно|срочно|неважно)\b)",
                body,
                re.IGNORECASE,
            )
            reminders = None
            if reminder_match:
                parsed_reminders = parse_reminder_minutes(reminder_match.group(1))
                reminders = parsed_reminders if parsed_reminders else None
                body = (body[: reminder_match.start()] + body[reminder_match.end() :]).strip()
            no_due = bool(
                re.search(
                    r"(?:\s+|^)(?:без\s+(?:срока|даты)|no\s+(?:due\s+date|deadline))\s*$",
                    body,
                    re.IGNORECASE,
                )
            )
            if no_due:
                body = re.sub(
                    r"(?:\s+|^)(?:без\s+(?:срока|даты)|no\s+(?:due\s+date|deadline))\s*$",
                    "",
                    body,
                    flags=re.IGNORECASE,
                ).strip(" ,")
            time_first = re.match(
                r"^(?:в|at)\s+"
                r"((?:[01]?\d|2[0-3])(?:[.:][0-5]\d)?"
                r"(?:\s*(?:час(?:а|ов)?|am|pm|утра|дня|вечера|ночи))?)\s+(.+)$",
                body,
                re.IGNORECASE,
            )
            leading_relative = re.match(
                r"^(сегодня|завтра|послезавтра|today|tomorrow)\b\s*(.*)$",
                body,
                re.IGNORECASE,
            )
            natural_hour = (
                r"(?:[01]?\d|2[0-3])(?:[.:][0-5]\d)?"
                r"(?:\s*(?:час(?:а|ов)?|am|pm|утра|дня|вечера|ночи))?"
                r"|час\s+(?:утра|дня|вечера|ночи)"
            )
            temporal = re.search(
                r"\b(?:сегодня|завтра|послезавтра|today|tomorrow|"
                r"(?:в\s+)?(?:следующ(?:ий|ую|ее)|next)\s+"
                r"(?:понедельник|вторник|среду|четверг|пятницу|субботу|воскресенье|"
                r"monday|tuesday|wednesday|thursday|friday|saturday|sunday)|"
                r"(?:в\s+)?(?:понедельник|вторник|среду|четверг|пятницу|субботу|"
                r"воскресенье|monday|tuesday|wednesday|thursday|friday|saturday|sunday)|"
                r"\d{1,2}[./-]\d{1,2}(?:[./-]\d{2,4})?)\b.*$",
                body,
                re.IGNORECASE,
            )
            if time_first:
                when_text = f"в {time_first.group(1)}"
                title = time_first.group(2).strip(" ,")
            elif leading_relative:
                remainder = leading_relative.group(2).strip()
                time_in_remainder = re.search(
                    rf"\bв\s+({natural_hour})\b",
                    remainder,
                    re.IGNORECASE,
                )
                when_text = leading_relative.group(1)
                if time_in_remainder:
                    when_text += f" в {time_in_remainder.group(1)}"
                    title = (
                        remainder[: time_in_remainder.start()]
                        + remainder[time_in_remainder.end() :]
                    ).strip(" ,")
                else:
                    title = remainder.strip(" ,")
            else:
                when_text = temporal.group(0).strip() if temporal else None
                title = body[: temporal.start()].strip(" ,") if temporal else body
            return Intent(
                action="create",
                title=title,
                when_text=when_text,
                no_due=no_due,
                priority=priority,
                reminders=reminders,
            )
        return Intent(action="help")


class OpenAIIntentParser(IntentParser):
    def __init__(self, settings: Settings):
        self.client = OpenAI(
            api_key=settings.openai_api_key.get_secret_value(),
            max_retries=0,
            timeout=5,
        )
        self.model = settings.openai_model

    def parse(self, text: str, language: str, timezone: str) -> Intent:
        response = self.client.responses.parse(
            model=self.model,
            instructions=(
                "Extract a task-management intent. Never calculate or normalize dates; preserve date "
                "phrases verbatim in when_text. Do not invent missing values. "
                f"The user's language is {language}, timezone is {timezone}."
            ),
            input=text,
            text_format=Intent,
        )
        if response.output_parsed is None:
            raise ValueError("Model returned no structured intent")
        return response.output_parsed


class CompositeIntentParser(IntentParser):
    def __init__(self, settings: Settings):
        self.rules = RuleIntentParser()
        self.llm = (
            OpenAIIntentParser(settings) if settings.openai_api_key.get_secret_value() else None
        )

    def parse(self, text: str, language: str, timezone: str) -> Intent:
        rule_intent = self.rules.parse(text, language, timezone)
        if rule_intent.action != "help":
            return rule_intent
        if self.llm:
            try:
                return self.llm.parse(text, language, timezone)
            except Exception:
                pass
        return rule_intent
