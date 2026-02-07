import json

import httpx
import pytest

from app.extractor import EventExtractor, OPENAI_API_URL


SAMPLE_EVENTS = [
    {
        "title": "AI Meetup",
        "url": "https://datatalk.cz/event/ai-meetup",
        "date_text": "2025-03-15",
        "description": "An evening of AI talks.",
    }
]

MOCK_OPENAI_RESPONSE = {
    "choices": [
        {
            "message": {
                "content": json.dumps(
                    [
                        {
                            "title": "AI Meetup",
                            "date": "2025-03-15",
                            "location": "Prague",
                            "topics": ["AI"],
                            "type": "meetup",
                            "level": None,
                            "language": "en",
                            "url": "https://datatalk.cz/event/ai-meetup",
                            "description": "An evening of AI talks.",
                        }
                    ]
                )
            }
        }
    ]
}


class TestExtractor:
    @pytest.mark.anyio
    async def test_extract_without_api_key(self, monkeypatch):
        """Without an API key, extractor returns raw events unchanged."""
        monkeypatch.setenv("OPENAI_API_KEY", "")
        # Clear the cached settings so the monkeypatched env is picked up
        from app.config import get_settings

        get_settings.cache_clear()
        try:
            extractor = EventExtractor()
            result = await extractor.extract(SAMPLE_EVENTS)
            assert result == SAMPLE_EVENTS
        finally:
            get_settings.cache_clear()

    @pytest.mark.anyio
    async def test_extract_with_mock_openai(self, monkeypatch, respx_mock):
        """With a mocked OpenAI API, extractor returns parsed JSON."""
        monkeypatch.setenv("OPENAI_API_KEY", "test-key-123")
        from app.config import get_settings

        get_settings.cache_clear()
        try:
            respx_mock.post(OPENAI_API_URL).mock(
                return_value=httpx.Response(200, json=MOCK_OPENAI_RESPONSE)
            )

            extractor = EventExtractor()
            result = await extractor.extract(SAMPLE_EVENTS)

            assert len(result) == 1
            assert result[0]["title"] == "AI Meetup"
            assert result[0]["location"] == "Prague"
            assert result[0]["topics"] == ["AI"]
            assert result[0]["type"] == "meetup"
        finally:
            get_settings.cache_clear()
