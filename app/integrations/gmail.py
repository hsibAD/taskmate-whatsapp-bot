import base64
import json
from email.message import EmailMessage
from pathlib import Path
from typing import ClassVar

from cryptography.fernet import Fernet
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from app.config import Settings


class GmailClient:
    SCOPES: ClassVar[list[str]] = [
        "https://www.googleapis.com/auth/gmail.readonly",
        "https://www.googleapis.com/auth/gmail.send",
    ]

    def __init__(self, settings: Settings):
        self.settings = settings

    def _credentials(self) -> Credentials:
        encrypted_path = Path(self.settings.gmail_credentials_file + ".token")
        key = self.settings.gmail_token_encryption_key.get_secret_value()
        if not key or not encrypted_path.exists():
            raise RuntimeError("Encrypted Gmail OAuth token is not configured")
        token_info = json.loads(Fernet(key.encode()).decrypt(encrypted_path.read_bytes()))
        return Credentials.from_authorized_user_info(token_info, self.SCOPES)

    def service(self):
        return build("gmail", "v1", credentials=self._credentials(), cache_discovery=False)

    def get_message(self, message_id: str) -> dict:
        return (
            self.service()
            .users()
            .messages()
            .get(userId="me", id=message_id, format="full")
            .execute()
        )

    def history(self, start_history_id: str) -> tuple[list[str], str | None]:
        service = self.service()
        message_ids: set[str] = set()
        page_token = None
        latest_history_id = None
        while True:
            response = (
                service.users()
                .history()
                .list(
                    userId="me",
                    startHistoryId=start_history_id,
                    historyTypes=["messageAdded"],
                    pageToken=page_token,
                )
                .execute()
            )
            latest_history_id = response.get("historyId", latest_history_id)
            message_ids.update(
                item["message"]["id"]
                for history in response.get("history", [])
                for item in history.get("messagesAdded", [])
            )
            page_token = response.get("nextPageToken")
            if not page_token:
                break
        return sorted(message_ids), latest_history_id

    def profile(self) -> dict:
        return self.service().users().getProfile(userId="me").execute()

    def watch(self) -> dict:
        return (
            self.service()
            .users()
            .watch(
                userId="me",
                body={
                    "topicName": self.settings.gmail_pubsub_topic,
                    "labelIds": ["INBOX"],
                    "labelFilterBehavior": "INCLUDE",
                },
            )
            .execute()
        )

    def send_email(self, recipient: str, subject: str, body: str) -> dict:
        message = EmailMessage()
        message["To"] = recipient
        message["From"] = self.settings.gmail_bot_address
        message["Subject"] = subject
        message.set_content(body)
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        return self.service().users().messages().send(userId="me", body={"raw": raw}).execute()
