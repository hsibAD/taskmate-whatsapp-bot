import re
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import (
    ConversationState,
    InboundEmail,
    Priority,
    Task,
    TaskStatus,
    User,
    UserEmail,
)
from app.schemas import Intent, ParsedEvent
from app.services.email_events import confirm_email_event, stage_email_event
from app.services.intents import IntentParser
from app.services.onboarding import begin_email_verification, confirm_email, onboarding_reply
from app.services.reminders import parse_reminder_minutes
from app.services.tasks import complete_task, create_task, find_tasks, reschedule_task, summary
from app.services.time import (
    TimeParseError,
    format_local,
    has_explicit_time,
    parse_future_datetime,
    validate_timezone,
)


class BotService:
    HELP_MENU_RU = "__TASKMATE_HELP_MENU_RU__"
    HELP_MENU_EN = "__TASKMATE_HELP_MENU_EN__"

    def __init__(self, settings: Settings, parser: IntentParser):
        self.settings = settings
        self.parser = parser

    def handle(self, db: Session, whatsapp_id: str, text: str) -> str:
        user = db.scalar(select(User).where(User.whatsapp_id == whatsapp_id))
        if not user:
            user = User(whatsapp_id=whatsapp_id)
            db.add(user)
            db.flush()
        user.last_inbound_at = datetime.now(UTC)
        if user.onboarding_step != "complete":
            reply = onboarding_reply(user, text, self.settings)
            db.commit()
            return reply or "RU / EN"

        state = db.get(ConversationState, user.id)
        starts_new_command = bool(
            re.match(
                r"^\s*(?:добавь|создай|напомни\s+мне|add|create|remind\s+me)\b",
                text,
                re.IGNORECASE,
            )
        )
        if state and starts_new_command:
            db.delete(state)
            db.flush()
            state = None
        capability_phrases = {
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
        }
        if text.strip().casefold() in capability_phrases:
            db.commit()
            return self.HELP_MENU_RU if user.language.value == "ru" else self.HELP_MENU_EN

        email_help_phrases = (
            r"как\s+(?:мне\s+)?(?:отправить|переслать)\s+тебе\s+письмо",
            r"куда\s+(?:мне\s+)?(?:отправить|переслать)\s+письмо",
            r"как\s+(?:добавить|создать)\s+(?:задачу|встречу)\s+из\s+письма",
            r"как\s+работает\s+почта",
            r"помощь\s+(?:с\s+)?почтой",
            r"email\s+help",
            r"how\s+do\s+i\s+(?:send|forward)\s+(?:you\s+)?an?\s+email",
        )
        if any(re.search(pattern, text, re.IGNORECASE) for pattern in email_help_phrases):
            db.commit()
            return self._email_instructions(db, user)

        if text == "__menu_add_task__":
            if state:
                db.delete(state)
                db.flush()
            db.merge(
                ConversationState(
                    user_id=user.id,
                    state="new_task_title",
                    payload={},
                )
            )
            db.commit()
            return (
                "Отлично! Что нужно сделать? Например: «позвонить врачу»."
                if user.language.value == "ru"
                else "Great! What do you need to do? For example: “call the doctor”."
            )
        if text in {"__menu_tasks__", "__menu_day_summary__"}:
            if state:
                db.delete(state)
                db.flush()
            text = "задачи" if text == "__menu_tasks__" else "сводка на день"
            state = None

        if state:
            reply = self._handle_state(db, user, state, text)
            db.commit()
            return reply

        timezone_match = re.search(
            r"(?:смени(?:ть)?|замени(?:ть)?|измени(?:ть)?|установи(?:ть)?)\s+"
            r"(?:мой\s+)?часов(?:ой|ого)\s+пояс(?:а)?(?:\s+на)?\s*"
            r"(.*?)\s*$",
            text,
            re.IGNORECASE,
        )
        if timezone_match:
            requested_timezone = timezone_match.group(1)
            if not requested_timezone:
                db.merge(ConversationState(user_id=user.id, state="change_timezone", payload={}))
                db.commit()
                return (
                    "Укажите новый часовой пояс, например Europe/Paris или Asia/Tokyo. "
                    "Сроки старых задач не изменятся."
                    if user.language.value == "ru"
                    else "Enter the new timezone, for example Europe/Paris or Asia/Tokyo. "
                    "Existing task deadlines will not change."
                )
            return self._change_timezone(db, user, requested_timezone)

        replace_email_match = re.search(
            r"(?:смени(?:ть)?|замени(?:ть)?|измени(?:ть)?)\s+"
            r"(?:мою\s+)?почт(?:у|ы)(?:\s+на)?\s*"
            r"([A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,})?",
            text,
            re.IGNORECASE,
        )
        if replace_email_match:
            requested_email = replace_email_match.group(1)
            if not requested_email:
                db.merge(ConversationState(user_id=user.id, state="change_email", payload={}))
                db.commit()
                return (
                    "Напишите новый адрес почты. После подтверждения он заменит текущую почту."
                    if user.language.value == "ru"
                    else "Send the new email address. It will replace the current email after "
                    "verification."
                )
            return self._begin_email_change(db, user, requested_email)

        email_match = re.search(
            r"(?:^email\s+|(?:моя\s+)?почта\s*:?\s*)"
            r"([A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,})",
            text,
            re.IGNORECASE,
        )
        if email_match:
            requested_email = email_match.group(1).casefold()
            existing = db.scalar(
                select(UserEmail).where(
                    UserEmail.user_id == user.id,
                    UserEmail.email == requested_email,
                    UserEmail.verified.is_(True),
                )
            )
            if existing:
                db.commit()
                return (
                    f"Почта {requested_email} уже подтверждена и привязана."
                    if user.language.value == "ru"
                    else f"Email {requested_email} is already verified and linked."
                )
            record, code = begin_email_verification(db, user, requested_email, self.settings)
            db.flush()
            db.add(ConversationState(user_id=user.id, state="email_otp", payload={"id": record.id}))
            db.commit()
            if self.settings.environment == "development":
                delivery = f" DEV-CODE: {code}"
            else:
                from app.worker import send_verification_email

                send_verification_email.delay(record.email, code, user.language.value)
                delivery = ""
            return (
                f"Код отправлен на {record.email}. Введите его.{delivery}"
                if user.language.value == "ru"
                else f"Code sent to {record.email}. Enter it.{delivery}"
            )

        intent = self.parser.parse(text, user.language.value, user.timezone)
        reply = self._apply_intent(db, user, intent)
        db.commit()
        return reply

    def _handle_state(self, db: Session, user: User, state: ConversationState, text: str) -> str:
        ru = user.language.value == "ru"
        if state.state == "email_otp":
            record = db.get(UserEmail, state.payload["id"])
            if record and confirm_email(record, text):
                if state.payload.get("replace"):
                    old_records = list(
                        db.scalars(
                            select(UserEmail).where(
                                UserEmail.user_id == user.id,
                                UserEmail.id != record.id,
                            )
                        ).all()
                    )
                    for old_record in old_records:
                        db.delete(old_record)
                db.delete(state)
                return (
                    f"Почта заменена на {record.email}."
                    if ru and state.payload.get("replace")
                    else "Почта подтверждена."
                    if ru
                    else f"Email changed to {record.email}."
                    if state.payload.get("replace")
                    else "Email verified."
                )
            return "Неверный или просроченный код." if ru else "Invalid or expired code."
        if state.state == "new_task_title":
            title = text.strip()
            if not title:
                return "Напишите, как называется задача." if ru else "Tell me the task name."
            state.state = "new_task_due"
            state.payload = Intent(action="create", title=title).model_dump(mode="json")
            return (
                f"Записал: «{title}». На какой день и время поставить задачу?"
                if ru
                else f"Got it: “{title}”. What date and time should I use?"
            )
        if state.state == "change_timezone":
            return self._change_timezone(db, user, text)
        if state.state == "change_email":
            email_match = re.search(
                r"([A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,})",
                text,
                re.IGNORECASE,
            )
            if not email_match:
                return (
                    "Не вижу адрес почты. Например: name@example.com"
                    if ru
                    else "I could not find an email address. For example: name@example.com"
                )
            db.delete(state)
            db.flush()
            return self._begin_email_change(db, user, email_match.group(1))
        if state.state == "email_event_confirmation":
            normalized = text.strip().casefold()
            if normalized not in {"да", "yes", "нет", "no"}:
                return "Ответьте ДА или НЕТ." if ru else "Reply YES or NO."
            _, reply = confirm_email_event(db, state, normalized in {"да", "yes"})
            return reply
        if state.state == "email_event_details":
            payload = state.payload
            original = payload.get("when_text")
            candidate = f"{original} {text}" if original else text
            try:
                start_at = parse_future_datetime(
                    candidate,
                    user.timezone,
                    language=user.language.value,
                )
            except TimeParseError:
                return (
                    "Не удалось понять дату и время. Напишите, например: "
                    "«завтра в 15:00» или «3 августа в 10 утра»."
                    if ru
                    else "I could not understand the date and time. Try "
                    "“tomorrow at 3 pm” or “August 3 at 10 am”."
                )
            if not has_explicit_time(candidate):
                state.payload = {**payload, "when_text": candidate}
                return (
                    "Дата понятна. Во сколько состоится событие?"
                    if ru
                    else "I understood the date. What time is the event?"
                )
            record = db.get(InboundEmail, payload["email_id"])
            if not record:
                db.delete(state)
                return "Письмо больше недоступно." if ru else "The email is no longer available."
            extracted = record.extracted or {}
            event = ParsedEvent(
                title=extracted.get("title") or record.subject or "Событие из письма",
                start_at=start_at,
                timezone=user.timezone,
                confidence=0.8,
            )
            _, _, prompt = stage_email_event(db, record, user, event)
            return prompt or ("Данные события сохранены." if ru else "Event details were saved.")
        if state.state == "email_event_reminders":
            task = db.get(Task, state.payload["task_id"])
            minutes = parse_reminder_minutes(text)
            if minutes == []:
                return (
                    "Не понял интервалы. Напишите, например: «за день и за час», "
                    "«за 30 минут», «в момент события» или «по умолчанию»."
                    if ru
                    else "I could not understand the intervals. Try “one day and one hour”, "
                    "“30 minutes”, “at the event time”, or “default”."
                )
            from app.services.tasks import schedule_reminders

            selected = minutes if minutes is not None else user.default_reminders
            schedule_reminders(db, task, selected)
            db.delete(state)
            return (
                "Напоминания сохранены: " + self._format_reminder_intervals(selected, ru) + "."
                if ru
                else "Reminders saved: " + self._format_reminder_intervals(selected, ru) + "."
            )
        if state.state == "new_task_due":
            payload = state.payload
            original = payload.get("when_text")
            candidate = f"{original} {text}" if original else text
            try:
                parse_future_datetime(candidate, user.timezone, language=user.language.value)
            except TimeParseError:
                return (
                    "Не удалось понять дату и время. Например: «в следующий понедельник в 3 часа дня»."
                    if ru
                    else "I could not understand that. For example: “next Monday at 3 pm”."
                )
            if not has_explicit_time(candidate):
                state.payload = {**payload, "when_text": candidate}
                return (
                    "Во сколько выполнить задачу? Например: «в 3 часа дня»."
                    if ru
                    else "What time is the task due? For example: “at 3 pm”."
                )
            state.state = "new_task_reminders"
            state.payload = {**payload, "when_text": candidate}
            return (
                "За сколько предупредить? Например: «за день и за час» или «за 30 минут»."
                if ru
                else "When should I remind you? For example: “one day and one hour before”."
            )
        if state.state == "new_task_reminders":
            reminders = parse_reminder_minutes(text)
            if reminders == []:
                return (
                    "Не понял интервалы. Напишите, например: «за день и за час» или «за 30 минут»."
                    if ru
                    else "I did not understand. Try “one day and one hour” or “30 minutes”."
                )
            intent = Intent.model_validate(
                {**state.payload, "reminders": reminders or user.default_reminders}
            )
            try:
                task = create_task(db, user, intent)
            except TimeParseError:
                state.state = "new_task_due"
                return (
                    "Дата уже прошла или не распознана. Укажите новую дату и время."
                    if ru
                    else "That date has passed or is unclear. Enter a new date and time."
                )
            db.delete(state)
            return (
                f"Создано: {task.title} — {format_local(task.due_at, user.timezone, 'ru')}. "
                f"Напоминания: "
                f"{self._format_reminder_intervals(reminders or user.default_reminders, True, False)}."
                if ru
                else f"Created: {task.title} — {format_local(task.due_at, user.timezone, 'en')}. "
                f"Reminders: "
                f"{self._format_reminder_intervals(reminders or user.default_reminders, False, False)}."
            )
        if state.state == "task_choice":
            try:
                index = int(text.strip()) - 1
                task_id = state.payload["ids"][index]
            except (ValueError, IndexError):
                return "Введите номер из списка." if ru else "Enter a number from the list."
            task = db.get(Task, task_id)
            action = state.payload["action"]
            if action == "complete":
                complete_task(task)
            elif action == "delete":
                task.status = TaskStatus.CANCELLED
            elif action == "reschedule":
                reschedule_task(db, user, task, state.payload["when_text"])
            elif action == "set_priority":
                task.priority = Priority(state.payload["priority"])
            db.delete(state)
            return self._task_action_confirmation(user, task, action)
        return "Состояние сброшено." if ru else "State reset."

    def _apply_intent(self, db: Session, user: User, intent) -> str:
        ru = user.language.value == "ru"
        if intent.action == "help":
            return self.HELP_MENU_RU if ru else self.HELP_MENU_EN
        if intent.action == "create":
            payload = intent.model_dump(mode="json")
            if intent.no_due:
                task = create_task(db, user, intent)
                return (
                    f"Создано без срока: {task.title}."
                    if ru
                    else f"Created without a due date: {task.title}."
                )
            if not intent.when_text:
                db.merge(ConversationState(user_id=user.id, state="new_task_due", payload=payload))
                return (
                    "На какой день и время поставить задачу?"
                    if ru
                    else "What date and time should I use?"
                )
            try:
                parse_future_datetime(intent.when_text, user.timezone, language=user.language.value)
            except TimeParseError:
                db.merge(ConversationState(user_id=user.id, state="new_task_due", payload=payload))
                return (
                    "Не удалось понять дату. Укажите день и время, например "
                    "«в следующий понедельник в 3 часа дня»."
                    if ru
                    else "I could not understand the date. Try “next Monday at 3 pm”."
                )
            if not has_explicit_time(intent.when_text):
                db.merge(ConversationState(user_id=user.id, state="new_task_due", payload=payload))
                return (
                    "Во сколько выполнить задачу? Например: «в 3 часа дня»."
                    if ru
                    else "What time is the task due? For example: “at 3 pm”."
                )
            if intent.reminders is None:
                db.merge(
                    ConversationState(user_id=user.id, state="new_task_reminders", payload=payload)
                )
                return (
                    "За сколько предупредить? Например: «за день и за час» или «за 30 минут»."
                    if ru
                    else "When should I remind you? For example: “one day and one hour before”."
                )
            task = create_task(db, user, intent)
            return (
                f"Готово! Создано: {task.title} — "
                f"{format_local(task.due_at, task.timezone, 'ru')}.\n"
                f"Приоритет: "
                f"{'🔴 высокий' if task.priority == Priority.HIGH else '🟢 низкий' if task.priority == Priority.LOW else '🟡 обычный'}.\n"
                f"Напоминания: "
                f"{self._format_reminder_intervals(intent.reminders or user.default_reminders, True, False)}."
                if ru
                else f"Done! Created: {task.title} — "
                f"{format_local(task.due_at, task.timezone, 'en')}.\n"
                f"Priority: {task.priority.value}.\n"
                f"Reminders: "
                f"{self._format_reminder_intervals(intent.reminders or user.default_reminders, False, False)}."
            )
        if intent.action == "summary":
            return summary(db, user, intent.period or "day")
        if intent.action == "list":
            tasks = list(
                db.scalars(
                    select(Task)
                    .where(
                        Task.user_id == user.id,
                        Task.status == TaskStatus.PENDING,
                    )
                    .order_by(Task.due_at.asc().nullslast())
                ).all()
            )
            if not tasks:
                return "Задач нет." if ru else "No tasks."
            return "\n".join(
                f"{i}. {task.title} — "
                f"{format_local(task.due_at, task.timezone, user.language.value)}"
                for i, task in enumerate(tasks, 1)
            )
        if intent.action in {"complete", "delete", "reschedule", "set_priority"}:
            matches = find_tasks(db, user, intent.task_ref or intent.title or "")
            if not matches:
                return "Задача не найдена." if ru else "Task not found."
            if len(matches) > 1:
                db.merge(
                    ConversationState(
                        user_id=user.id,
                        state="task_choice",
                        payload={
                            "ids": [task.id for task in matches],
                            "action": intent.action,
                            "when_text": intent.when_text,
                            "priority": intent.priority.value,
                        },
                    )
                )
                heading = "Выберите задачу:" if ru else "Choose a task:"
                return (
                    heading
                    + "\n"
                    + "\n".join(
                        f"{i}. {task.title} — "
                        f"{format_local(task.due_at, task.timezone, user.language.value)}"
                        for i, task in enumerate(matches, 1)
                    )
                )
            task = matches[0]
            if intent.action == "complete":
                complete_task(task)
            elif intent.action == "delete":
                task.status = TaskStatus.CANCELLED
            elif intent.action == "reschedule":
                reschedule_task(db, user, task, intent.when_text or "")
            else:
                task.priority = Priority(intent.priority)
            return self._task_action_confirmation(user, task, intent.action)
        return "Не понял команду." if ru else "I did not understand that command."

    @staticmethod
    def _task_action_confirmation(user: User, task: Task, action: str) -> str:
        ru = user.language.value == "ru"
        if action == "reschedule":
            when = format_local(task.due_at, task.timezone, user.language.value)
            return (
                f"Перенесено: «{task.title}» на {when}. Напоминания пересчитаны."
                if ru
                else f"Rescheduled “{task.title}” to {when}. Reminders were recalculated."
            )
        if action == "complete":
            return (
                f"Задача «{task.title}» отмечена выполненной."
                if ru
                else f"Task “{task.title}” marked complete."
            )
        if action == "delete":
            return f"Задача «{task.title}» удалена." if ru else f"Task “{task.title}” deleted."
        if action == "set_priority":
            return (
                f"Приоритет задачи «{task.title}» изменен на {task.priority.value}."
                if ru
                else f"Priority for “{task.title}” changed to {task.priority.value}."
            )
        return "Готово." if ru else "Done."

    def _change_timezone(self, db: Session, user: User, timezone: str) -> str:
        ru = user.language.value == "ru"
        command_match = re.search(
            r"(?:смени(?:ть)?|замени(?:ть)?|измени(?:ть)?|установи(?:ть)?)\s+"
            r"(?:мой\s+)?часов(?:ой|ого)\s+пояс(?:а)?(?:\s+на)?\s+(.+?)\s*$",
            timezone,
            re.IGNORECASE,
        )
        if command_match:
            timezone = command_match.group(1)
        try:
            new_timezone = validate_timezone(timezone.strip())
        except ValueError:
            return (
                "Неизвестный часовой пояс. Используйте формат Europe/Paris или Asia/Tokyo."
                if ru
                else "Unknown timezone. Use a name such as Europe/Paris or Asia/Tokyo."
            )
        old_timezone = user.timezone
        user.timezone = new_timezone
        state = db.get(ConversationState, user.id)
        if state and state.state == "change_timezone":
            db.delete(state)
        db.commit()
        return (
            f"Часовой пояс изменён: {old_timezone} → {new_timezone}. "
            "Старые задачи сохранили свои сроки и исходный часовой пояс. "
            "Новые задачи будут создаваться в новом часовом поясе."
            if ru
            else f"Timezone changed: {old_timezone} → {new_timezone}. Existing tasks kept their "
            "deadlines and original timezone. New tasks will use the new timezone."
        )

    def _begin_email_change(self, db: Session, user: User, email: str) -> str:
        ru = user.language.value == "ru"
        current = db.scalar(
            select(UserEmail).where(
                UserEmail.user_id == user.id,
                UserEmail.email == email.casefold(),
                UserEmail.verified.is_(True),
            )
        )
        if current:
            return (
                f"Почта {current.email} уже является текущей."
                if ru
                else f"{current.email} is already your current email."
            )
        try:
            record, code = begin_email_verification(db, user, email, self.settings)
        except ValueError:
            return (
                "Эта почта уже привязана к другому пользователю."
                if ru
                else "This email is already linked to another user."
            )
        db.flush()
        db.merge(
            ConversationState(
                user_id=user.id,
                state="email_otp",
                payload={"id": record.id, "replace": True},
            )
        )
        if self.settings.environment == "development":
            delivery = f" DEV-CODE: {code}"
        else:
            from app.worker import send_verification_email

            send_verification_email.delay(record.email, code, user.language.value)
            delivery = ""
        db.commit()
        return (
            f"Код отправлен на {record.email}. Введите его. Старая почта останется активной "
            f"до подтверждения.{delivery}"
            if ru
            else f"A code was sent to {record.email}. Enter it. Your old email remains active "
            f"until verification.{delivery}"
        )

    def _email_instructions(self, db: Session, user: User) -> str:
        ru = user.language.value == "ru"
        emails = list(
            db.scalars(
                select(UserEmail)
                .where(
                    UserEmail.user_id == user.id,
                    UserEmail.verified.is_(True),
                )
                .order_by(UserEmail.email)
            ).all()
        )
        bot_address = self.settings.gmail_bot_address or (
            "адрес пока не настроен" if ru else "address is not configured"
        )
        if ru:
            account = (
                "Ваша подтверждённая почта: " + ", ".join(record.email for record in emails) + "."
                if emails
                else "У вас пока нет подтверждённой почты. Чтобы зарегистрировать её, "
                "напишите: «Моя почта: name@example.com»."
            )
            return (
                "📧 Как добавить задачу или встречу из письма\n\n"
                f"1. Отправьте или перешлите письмо на: {bot_address}\n"
                "2. Отправляйте его только с подтверждённой почты — так я пойму, "
                "в чей список добавить событие.\n"
                "3. Можно указать всё прямо в теме, например:\n"
                "«Встреча с клиентом 3 августа в 15:00».\n"
                "4. Можно переслать обычное приглашение с датой и временем в тексте. "
                "Файл ICS полезен, но необязателен.\n"
                "5. Я пришлю найденные данные в WhatsApp и попрошу подтвердить добавление. "
                "Если даты или времени не хватает, уточню их здесь.\n\n" + account
            )
        account = (
            "Your verified email: " + ", ".join(record.email for record in emails) + "."
            if emails
            else "You do not have a verified email yet. To register one, send: "
            "“My email: name@example.com”."
        )
        return (
            "📧 How to add a task or meeting from email\n\n"
            f"1. Send or forward the email to: {bot_address}\n"
            "2. Send it from your verified email so I know whose list to use.\n"
            "3. You can put the details in the subject, for example: "
            "“Client meeting August 3 at 3 pm”.\n"
            "4. A normal invitation in the email body works too. ICS is helpful but optional.\n"
            "5. I will show the extracted details in WhatsApp and ask for confirmation. "
            "If something is missing, I will ask here.\n\n" + account
        )

    @staticmethod
    def _format_reminder_intervals(minutes: list[int], ru: bool, event: bool = True) -> str:
        def ru_form(amount: int, one: str, few: str, many: str) -> str:
            if amount % 10 == 1 and amount % 100 != 11:
                word = one
            elif amount % 10 in {2, 3, 4} and amount % 100 not in {12, 13, 14}:
                word = few
            else:
                word = many
            return f"{amount} {word}"

        def format_one(value: int) -> str:
            if value == 0:
                if ru:
                    return "в момент события" if event else "в момент задачи"
                return "at the event time" if event else "at the task time"
            if value % 1440 == 0:
                amount = value // 1440
                return (
                    f"за {ru_form(amount, 'день', 'дня', 'дней')}"
                    if ru
                    else f"{amount} day{'s' if amount != 1 else ''} before"
                )
            if value % 60 == 0:
                amount = value // 60
                return (
                    f"за {ru_form(amount, 'час', 'часа', 'часов')}"
                    if ru
                    else f"{amount} hour{'s' if amount != 1 else ''} before"
                )
            if value > 60:
                hours, remaining_minutes = divmod(value, 60)
                if ru:
                    return (
                        f"за {ru_form(hours, 'час', 'часа', 'часов')} "
                        f"{ru_form(remaining_minutes, 'минуту', 'минуты', 'минут')}"
                    )
                return (
                    f"{hours} hour{'s' if hours != 1 else ''} "
                    f"{remaining_minutes} minute{'s' if remaining_minutes != 1 else ''} before"
                )
            return (
                f"за {ru_form(value, 'минуту', 'минуты', 'минут')}"
                if ru
                else f"{value} minute{'s' if value != 1 else ''} before"
            )

        values = [format_one(value) for value in sorted(set(minutes) | {0}, reverse=True)]
        if len(values) == 1:
            return values[0]
        conjunction = " и " if ru else " and "
        return ", ".join(values[:-1]) + conjunction + values[-1]
