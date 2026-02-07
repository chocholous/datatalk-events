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

SAMPLE_ENRICHED_EVENTS = [
    {
        "title": "AI Meetup",
        "url": "https://datatalk.cz/event/ai-meetup",
        "date_text": "2025-03-15",
        "description": "An evening of AI talks.",
        "json_ld": {"@type": "Event", "name": "AI Meetup", "startDate": "2025-03-15"},
        "og_meta": {"og:title": "AI Meetup", "og:image": "https://example.com/img.jpg"},
        "markdown": "# AI Meetup\n\nGreat event about AI.",
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
                            "end_date": None,
                            "location": "Prague",
                            "topics": ["AI"],
                            "type": "meetup",
                            "level": None,
                            "language": "en",
                            "url": "https://datatalk.cz/event/ai-meetup",
                            "description": "An evening of AI talks.",
                            "speakers": ["Dr. Smith"],
                            "organizer": "DataTalk",
                            "image_url": "https://example.com/img.jpg",
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
            assert result[0]["speakers"] == ["Dr. Smith"]
            assert result[0]["organizer"] == "DataTalk"
            assert result[0]["image_url"] == "https://example.com/img.jpg"
        finally:
            get_settings.cache_clear()

    @pytest.mark.anyio
    async def test_extractor_formats_enriched_payload(self, monkeypatch, respx_mock):
        """Verify payload sent to OpenAI includes json_ld, og_meta, markdown."""
        monkeypatch.setenv("OPENAI_API_KEY", "test-key-123")
        from app.config import get_settings

        get_settings.cache_clear()
        try:
            captured_request = {}

            def capture_request(request):
                captured_request["body"] = json.loads(request.content)
                return httpx.Response(200, json=MOCK_OPENAI_RESPONSE)

            respx_mock.post(OPENAI_API_URL).mock(side_effect=capture_request)

            extractor = EventExtractor()
            await extractor.extract(SAMPLE_ENRICHED_EVENTS)

            # Check payload sent to OpenAI
            content = captured_request["body"]["messages"][0]["content"]
            # The payload should contain json_ld, og_meta, markdown data
            assert "json_ld" in content
            assert "og_meta" in content
            assert "AI Meetup" in content
        finally:
            get_settings.cache_clear()

    @pytest.mark.anyio
    async def test_extractor_handles_missing_detail_data(self, monkeypatch, respx_mock):
        """Events without detail data (no json_ld, og_meta, markdown) don't break extraction."""
        monkeypatch.setenv("OPENAI_API_KEY", "test-key-123")
        from app.config import get_settings

        get_settings.cache_clear()
        try:
            # Events without any detail enrichment
            plain_events = [
                {
                    "title": "Plain Event",
                    "url": "https://example.com/plain",
                }
            ]

            respx_mock.post(OPENAI_API_URL).mock(
                return_value=httpx.Response(200, json=MOCK_OPENAI_RESPONSE)
            )

            extractor = EventExtractor()
            result = await extractor.extract(plain_events)

            assert len(result) == 1
        finally:
            get_settings.cache_clear()
