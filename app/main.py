import base64
import json
import logging
import time
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token
from prometheus_client import CONTENT_TYPE_LATEST, Counter, generate_latest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_db
from app.integrations.whatsapp import WhatsAppClient, extract_messages
from app.models import WebhookEvent
from app.services.bot import BotService
from app.services.intents import CompositeIntentParser
from app.worker import process_gmail_history

logging.basicConfig(
    level=logging.INFO,
    format='{"time":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","message":"%(message)s"}',
)
logger = logging.getLogger(__name__)
webhooks_total = Counter("taskmate_webhooks_total", "Webhook events", ["provider", "status"])


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    app.state.settings = settings
    app.state.whatsapp = WhatsAppClient(settings)
    app.state.bot = BotService(settings, CompositeIntentParser(settings))
    yield
    app.state.whatsapp.close()


app = FastAPI(title="TaskMate Bot", version="0.1.0", lifespan=lifespan)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/ready")
def ready(db: Session = Depends(get_db)) -> dict:
    db.execute(text("SELECT 1"))
    return {"status": "ready"}


@app.get("/metrics")
def metrics(
    authorization: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> Response:
    _require_service_token(authorization, settings)
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/webhooks/whatsapp")
@app.get("/whatsapp")
def verify_whatsapp(
    mode: str = Query(alias="hub.mode"),
    verify_token: str = Query(alias="hub.verify_token"),
    challenge: str = Query(alias="hub.challenge"),
    settings: Settings = Depends(get_settings),
) -> Response:
    if mode != "subscribe" or verify_token != settings.meta_verify_token.get_secret_value():
        raise HTTPException(status_code=403, detail="verification failed")
    return Response(challenge, media_type="text/plain")


@app.post("/webhooks/whatsapp", status_code=200)
@app.post("/whatsapp", status_code=200)
async def whatsapp_webhook(
    request: Request,
    db: Session = Depends(get_db),
    x_hub_signature_256: str | None = Header(default=None),
) -> dict:
    body = await request.body()
    if not request.app.state.whatsapp.verify_signature(body, x_hub_signature_256):
        webhooks_total.labels("whatsapp", "invalid_signature").inc()
        raise HTTPException(status_code=401, detail="invalid signature")
    payload = json.loads(body)
    for sender, message, event_id in extract_messages(payload):
        started_at = time.monotonic()
        if db.get(WebhookEvent, {"provider": "whatsapp", "event_id": event_id}):
            continue
        db.add(WebhookEvent(provider="whatsapp", event_id=event_id))
        try:
            reply = request.app.state.bot.handle(db, sender, message)
            if reply in {
                BotService.HELP_MENU_RU,
                BotService.HELP_MENU_EN,
            }:
                language = "ru" if reply == BotService.HELP_MENU_RU else "en"
                request.app.state.whatsapp.send_main_menu(sender, language)
            else:
                request.app.state.whatsapp.send_text(sender, reply)
            webhooks_total.labels("whatsapp", "processed").inc()
            logger.info(
                "WhatsApp message processed event=%s duration_ms=%d",
                event_id,
                (time.monotonic() - started_at) * 1000,
            )
        except Exception:
            # The inbound event is valid and must be acknowledged even when the
            # outbound Graph API is temporarily unavailable. Meta retries 5xx
            # webhooks, which would otherwise create duplicate conversations.
            logger.exception("WhatsApp outbound delivery failed")
            webhooks_total.labels("whatsapp", "failed").inc()
    db.commit()
    return {"ok": True}


@app.post("/webhooks/gmail", status_code=202)
async def gmail_webhook(
    request: Request,
    authorization: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> dict:
    if settings.gmail_pubsub_audience:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="missing Pub/Sub identity token")
        try:
            id_token.verify_oauth2_token(
                authorization.removeprefix("Bearer "),
                google_requests.Request(),
                audience=settings.gmail_pubsub_audience,
            )
        except Exception as exc:
            raise HTTPException(status_code=401, detail="invalid Pub/Sub identity token") from exc
    envelope = await request.json()
    try:
        data = json.loads(base64.b64decode(envelope["message"]["data"]))
        history_id = str(data["historyId"])
        email_address = str(data["emailAddress"]).casefold()
        event_id = envelope["message"]["messageId"]
    except (KeyError, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail="invalid Pub/Sub envelope") from exc
    process_gmail_history.delay(email_address, history_id)
    webhooks_total.labels("gmail", "queued").inc()
    return {"queued": True, "event_id": event_id}


@app.post("/internal/gmail/watch")
def renew_watch(
    authorization: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> dict:
    _require_service_token(authorization, settings)
    from app.worker import renew_gmail_watch

    result = renew_gmail_watch.delay()
    return {"queued": True, "task_id": result.id}


def _require_service_token(authorization: str | None, settings: Settings) -> None:
    expected = f"Bearer {settings.service_token.get_secret_value()}"
    if authorization != expected:
        raise HTTPException(status_code=401, detail="unauthorized")
