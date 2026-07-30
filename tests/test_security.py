import hashlib
import hmac
from unittest.mock import patch

import httpx

from app.config import Settings
from app.integrations.whatsapp import WhatsAppClient, extract_messages


def test_whatsapp_signature():
    settings = Settings(meta_app_secret="secret")
    body = b'{"object":"whatsapp_business_account"}'
    signature = "sha256=" + hmac.new(b"secret", body, hashlib.sha256).hexdigest()
    assert WhatsAppClient(settings).verify_signature(body, signature)
    assert not WhatsAppClient(settings).verify_signature(body, "sha256=bad")


def test_recipient_override():
    settings = Settings(whatsapp_recipient_overrides='{"77782304206":"787782304206"}')
    client = WhatsAppClient(settings)
    assert client.resolve_recipient("77782304206") == "787782304206"
    assert client.resolve_recipient("15551234567") == "15551234567"


def test_whatsapp_main_menu_payload():
    client = WhatsAppClient(Settings(_env_file=None, meta_phone_number_id=""))
    result = client.send_main_menu("15551234567", "ru")
    interactive = result["payload"]["interactive"]
    assert interactive["type"] == "button"
    assert [button["reply"]["id"] for button in interactive["action"]["buttons"]] == [
        "menu_add_task",
        "menu_tasks",
        "menu_day_summary",
    ]


def test_extract_whatsapp_button_reply():
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "from": "15551234567",
                                    "id": "wamid.button",
                                    "type": "interactive",
                                    "interactive": {
                                        "type": "button_reply",
                                        "button_reply": {
                                            "id": "menu_add_task",
                                            "title": "➕ Новая задача",
                                        },
                                    },
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }
    assert extract_messages(payload) == [
        ("15551234567", "__menu_add_task__", "wamid.button")
    ]


def test_whatsapp_retries_tls_connect_timeout():
    settings = Settings(
        _env_file=None,
        meta_phone_number_id="123",
        meta_access_token="token",
    )
    client = WhatsAppClient(settings)
    request = httpx.Request("POST", "https://graph.facebook.com")
    success = httpx.Response(
        200,
        request=request,
        json={"messages": [{"id": "wamid.test"}]},
    )
    with (
        patch(
            "app.integrations.whatsapp.httpx.post",
            side_effect=[
                httpx.ConnectTimeout("TLS timeout", request=request),
                success,
            ],
        ) as post,
        patch("app.integrations.whatsapp.time.sleep"),
    ):
        result = client.send_text("15551234567", "test")

    assert result["messages"][0]["id"] == "wamid.test"
    assert post.call_count == 2
