from app.config import Settings


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
        assert settings.telegram_bot_token == ""
        assert settings.telegram_channel_id == ""
        assert settings.google_calendar_id == ""
        assert settings.secret_key == ""
        assert settings.webhook_url == "http://localhost:8000"
        assert settings.admin_username == "admin"
        assert settings.admin_password == ""
