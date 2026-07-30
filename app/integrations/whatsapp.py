import hashlib
import hmac
import json
import time
from datetime import UTC, datetime, timedelta

import httpx

from app.config import Settings
from app.models import User


class WhatsAppAPIError(RuntimeError):
    def __init__(self, status_code: int, payload: dict):
        error = payload.get("error", {})
        safe = {
            key: error.get(key)
            for key in (
                "message",
                "type",
                "code",
                "error_subcode",
                "error_user_title",
                "error_user_msg",
                "error_data",
                "fbtrace_id",
            )
            if error.get(key) is not None
        }
        super().__init__(f"WhatsApp API HTTP {status_code}: {json.dumps(safe, ensure_ascii=False)}")
        self.status_code = status_code
        self.payload = safe


class WhatsAppClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.client = httpx.Client(
            timeout=httpx.Timeout(15, connect=10),
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        )

    def close(self) -> None:
        self.client.close()

    def verify_signature(self, body: bytes, signature: str | None) -> bool:
        if not signature or not signature.startswith("sha256="):
            return False
        expected = hmac.new(
            self.settings.meta_app_secret.get_secret_value().encode(),
            body,
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(signature[7:], expected)

    def send_text(self, recipient: str, text: str) -> dict:
        recipient = self.resolve_recipient(recipient)
        return self._post(
            {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": recipient,
                "type": "text",
                "text": {"preview_url": False, "body": text[:4096]},
            }
        )

    def send_main_menu(self, recipient: str, language: str) -> dict:
        recipient = self.resolve_recipient(recipient)
        ru = language == "ru"
        return self._post(
            {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": recipient,
                "type": "interactive",
                "interactive": {
                    "type": "button",
                    "body": {
                        "text": (
                            "Я помогу создавать и переносить задачи, вовремя напоминать о них, "
                            "показывать сводки и добавлять встречи из писем.\n\n"
                            "Что хотите сделать?"
                            if ru
                            else "I can create and reschedule tasks, send reminders, show summaries, "
                            "and add meetings from emails.\n\nWhat would you like to do?"
                        )
                    },
                    "footer": {
                        "text": (
                            "Можно также написать команду своими словами"
                            if ru
                            else "You can also type a request in your own words"
                        )
                    },
                    "action": {
                        "buttons": [
                            {
                                "type": "reply",
                                "reply": {
                                    "id": "menu_add_task",
                                    "title": "➕ Новая задача" if ru else "➕ New task",
                                },
                            },
                            {
                                "type": "reply",
                                "reply": {
                                    "id": "menu_tasks",
                                    "title": "📋 Мои задачи" if ru else "📋 My tasks",
                                },
                            },
                            {
                                "type": "reply",
                                "reply": {
                                    "id": "menu_day_summary",
                                    "title": "📊 Сводка дня" if ru else "📊 Daily summary",
                                },
                            },
                        ]
                    },
                },
            }
        )

    def send_reminder(self, user: User, body: str) -> dict:
        within_window = bool(
            user.last_inbound_at
            and user.last_inbound_at.replace(tzinfo=UTC) >= datetime.now(UTC) - timedelta(hours=24)
        )
        if within_window:
            return self.send_text(user.whatsapp_id, body)
        recipient = self.resolve_recipient(user.whatsapp_id)
        return self._post(
            {
                "messaging_product": "whatsapp",
                "to": recipient,
                "type": "template",
                "template": {
                    "name": self.settings.meta_reminder_template,
                    "language": {"code": user.language.value},
                    "components": [
                        {
                            "type": "body",
                            "parameters": [{"type": "text", "text": body[:1024]}],
                        }
                    ],
                },
            }
        )

    def resolve_recipient(self, inbound_whatsapp_id: str) -> str:
        return self.settings.recipient_overrides.get(inbound_whatsapp_id, inbound_whatsapp_id)

    def _post(self, payload: dict) -> dict:
        if not self.settings.meta_phone_number_id:
            return {"dry_run": True, "payload": payload}
        url = (
            f"https://graph.facebook.com/{self.settings.meta_api_version}/"
            f"{self.settings.meta_phone_number_id}/messages"
        )
        headers = {
            "Authorization": f"Bearer {self.settings.meta_access_token.get_secret_value()}"
        }
        response = None
        for attempt in range(3):
            try:
                response = self.client.post(
                    url,
                    headers=headers,
                    json=payload,
                )
                break
            except (httpx.ConnectError, httpx.ConnectTimeout):
                if attempt == 2:
                    raise
                time.sleep(0.5 * (2**attempt))
        assert response is not None
        payload = response.json()
        if response.is_error:
            raise WhatsAppAPIError(response.status_code, payload)
        return payload


def extract_messages(payload: dict) -> list[tuple[str, str, str]]:
    messages: list[tuple[str, str, str]] = []
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            for message in change.get("value", {}).get("messages", []):
                if message.get("type") == "text":
                    messages.append((message["from"], message["text"]["body"], message["id"]))
                elif message.get("type") == "interactive":
                    reply = message.get("interactive", {}).get("button_reply", {})
                    button_commands = {
                        "menu_add_task": "__menu_add_task__",
                        "menu_tasks": "__menu_tasks__",
                        "menu_day_summary": "__menu_day_summary__",
                    }
                    if reply.get("id") in button_commands:
                        messages.append(
                            (
                                message["from"],
                                button_commands[reply["id"]],
                                message["id"],
                            )
                        )
    return messages
