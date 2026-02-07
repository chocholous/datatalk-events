import logging
from enum import StrEnum
from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


class EmailProvider(StrEnum):
    RESEND = "resend"
    SENDGRID = "sendgrid"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    app_name: str = "DataTalk Events"
    debug: bool = False
    database_url: str = "sqlite:///data/app.db"
    scrape_url: str = "https://datatalk.cz/kalendar-akci/"
    scrape_schedule: str = "0 8 * * 1"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    email_provider: EmailProvider = EmailProvider.RESEND
    resend_api_key: str = ""
    sendgrid_api_key: str = ""
    email_from: str = "events@datatalk.cz"
    telegram_bot_token: str = ""
    secret_key: str = ""
    webhook_url: str = "http://localhost:8000"
    admin_username: str = "admin"
    admin_password: str = ""
    scrape_detail_concurrency: int = 5
    scrape_detail_timeout: int = 15

    @field_validator("secret_key")
    @classmethod
    def warn_empty_secret_key(cls, v: str) -> str:
        if not v:
            logger.warning(
                "SECRET_KEY is empty. Set a strong secret key for production use."
            )
        return v

    @field_validator("admin_password")
    @classmethod
    def warn_empty_admin_password(cls, v: str) -> str:
        if not v:
            logger.warning(
                "ADMIN_PASSWORD is empty. Set a strong password for production use."
            )
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()
