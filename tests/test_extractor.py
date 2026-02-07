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
    async def test_extract_without_api_key_uses_fallback(self, monkeypatch):
        """Without an API key, extractor uses fallback extraction from structured data."""
        monkeypatch.setenv("OPENAI_API_KEY", "")
        from app.config import get_settings

        get_settings.cache_clear()
        try:
            extractor = EventExtractor()
            result = await extractor.extract(SAMPLE_ENRICHED_EVENTS)
            assert len(result) == 1
            assert result[0]["title"] == "AI Meetup"
            assert result[0]["url"] == "https://datatalk.cz/event/ai-meetup"
            assert result[0]["date"] == "2025-03-15"
            assert result[0]["image_url"] == "https://example.com/img.jpg"
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


class TestFallbackExtraction:
    """Test _extract_from_structured_data fallback method."""

    def test_fallback_extracts_json_ld_fields(self):
        extractor = EventExtractor()
        event = {
            "title": "Raw Title",
            "url": "https://example.com/event",
            "json_ld": {
                "@type": "Event",
                "name": "JSON-LD Title",
                "startDate": "2025-06-01T10:00:00",
                "endDate": "2025-06-01T18:00:00",
                "location": {"name": "PVA Expo Praha"},
                "organizer": {"name": "DataTalk"},
                "description": "Popis z JSON-LD",
            },
            "og_meta": {},
        }
        result = extractor._extract_from_structured_data(event)
        assert result["title"] == "JSON-LD Title"
        assert result["date"] == "2025-06-01T10:00:00"
        assert result["end_date"] == "2025-06-01T18:00:00"
        assert result["location"] == "PVA Expo Praha"
        assert result["organizer"] == "DataTalk"
        assert result["description"] == "Popis z JSON-LD"

    def test_fallback_extracts_og_meta(self):
        extractor = EventExtractor()
        event = {
            "title": "Raw Title",
            "url": "https://example.com/event",
            "json_ld": None,
            "og_meta": {
                "og:title": "OG Title",
                "og:description": "OG popis",
                "og:image": "https://example.com/og.jpg",
            },
        }
        result = extractor._extract_from_structured_data(event)
        assert result["title"] == "OG Title"
        assert result["description"] == "OG popis"
        assert result["image_url"] == "https://example.com/og.jpg"

    def test_fallback_handles_no_structured_data(self):
        extractor = EventExtractor()
        event = {
            "title": "Basic Event",
            "url": "https://example.com/basic",
            "description": "Raw description",
        }
        result = extractor._extract_from_structured_data(event)
        assert result["title"] == "Basic Event"
        assert result["url"] == "https://example.com/basic"
        assert result["description"] == "Raw description"
        assert result["location"] is None
        assert result["organizer"] is None
        assert result["speakers"] == []
        assert result["image_url"] is None

    def test_fallback_extracts_performers_as_speakers(self):
        extractor = EventExtractor()
        event = {
            "title": "Event",
            "url": "https://example.com/ev",
            "json_ld": {
                "performer": [
                    {"@type": "Person", "name": "Alice"},
                    {"@type": "Person", "name": "Bob"},
                ],
            },
            "og_meta": {},
        }
        result = extractor._extract_from_structured_data(event)
        assert result["speakers"] == ["Alice", "Bob"]

    def test_fallback_location_address_locality(self):
        extractor = EventExtractor()
        event = {
            "title": "Event",
            "url": "https://example.com/ev",
            "json_ld": {
                "location": {
                    "address": {"addressLocality": "Praha"},
                },
            },
            "og_meta": {},
        }
        result = extractor._extract_from_structured_data(event)
        assert result["location"] == "Praha"
