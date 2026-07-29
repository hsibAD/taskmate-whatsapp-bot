import json
from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: str = "development"
    database_url: str = "postgresql+psycopg://taskmate:taskmate@db:5432/taskmate"
    redis_url: str = "redis://redis:6379/0"
    public_base_url: str = "http://localhost:8000"
    default_timezone: str = "UTC"
    default_reminders_minutes: str = "1440,60"

    meta_verify_token: SecretStr = SecretStr("change-me")
    meta_app_secret: SecretStr = SecretStr("change-me")
    meta_access_token: SecretStr = SecretStr("")
    meta_phone_number_id: str = ""
    meta_api_version: str = "v23.0"
    meta_reminder_template: str = "task_reminder"
    whatsapp_recipient_overrides: str = "{}"

    openai_api_key: SecretStr = SecretStr("")
    openai_model: str = "gpt-5-mini"

    gmail_credentials_file: str = "/run/secrets/google-oauth.json"
    gmail_token_encryption_key: SecretStr = SecretStr("")
    gmail_pubsub_audience: str = ""
    gmail_pubsub_topic: str = ""
    gmail_bot_address: str = ""

    service_token: SecretStr = SecretStr("change-me")
    otp_ttl_minutes: int = Field(default=10, ge=2, le=60)
    email_excerpt_max_chars: int = Field(default=300, ge=0, le=1000)

    @property
    def default_reminders(self) -> list[int]:
        return sorted(
            {
                int(value.strip())
                for value in self.default_reminders_minutes.split(",")
                if value.strip()
            },
            reverse=True,
        )

    @property
    def recipient_overrides(self) -> dict[str, str]:
        value = json.loads(self.whatsapp_recipient_overrides)
        if not isinstance(value, dict):
            raise TypeError("WHATSAPP_RECIPIENT_OVERRIDES must be a JSON object")
        return {str(source): str(target) for source, target in value.items()}


@lru_cache
def get_settings() -> Settings:
    return Settings()
