import pytest
from pydantic import ValidationError

from app.config import EmailProvider, Settings


class TestSettings:
    def test_settings_loads_with_defaults(self) -> None:
        settings = Settings()
        assert settings.app_name == "DataTalk Events"
        assert settings.debug is False
        assert settings.database_url == "sqlite:///data/app.db"
        assert settings.scrape_url == "https://datatalk.cz/kalendar-akci/"
        assert settings.scrape_schedule == "0 8 * * 1"
        assert settings.openai_api_key == ""
        assert settings.openai_model == "gpt-4o-mini"
        assert settings.email_provider == EmailProvider.RESEND
        assert settings.resend_api_key == ""
        assert settings.sendgrid_api_key == ""
        assert settings.email_from == "events@datatalk.cz"
        assert settings.telegram_bot_token == ""
        assert settings.secret_key == ""
        assert settings.webhook_url == "http://localhost:8000"
        assert settings.admin_username == "admin"
        assert settings.admin_password == ""

    def test_email_provider_accepts_resend(self) -> None:
        settings = Settings(email_provider="resend")
        assert settings.email_provider == EmailProvider.RESEND

    def test_email_provider_accepts_sendgrid(self) -> None:
        settings = Settings(email_provider="sendgrid")
        assert settings.email_provider == EmailProvider.SENDGRID

    def test_email_provider_rejects_invalid(self) -> None:
        with pytest.raises(ValidationError):
            Settings(email_provider="mailgun")
