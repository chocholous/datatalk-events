from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.event_enricher import EventEnricher, _is_complete, _missing_fields


class TestCompleteness:
    def test_complete_event(self):
        event = {
            "date": "2026-03-15T18:00:00",
            "location": "Praha",
            "speakers": ["Jan Novák"],
            "description": "Skvělý event o AI.",
        }
        assert _is_complete(event) is True
        assert _missing_fields(event) == []

    def test_missing_speakers(self):
        event = {
            "date": "2026-03-15T18:00:00",
            "location": "Praha",
            "speakers": [],
            "description": "Event bez speakerů.",
        }
        assert _is_complete(event) is False
        assert "speakers" in _missing_fields(event)

    def test_missing_date(self):
        event = {
            "date": None,
            "location": "Praha",
            "speakers": ["Jan"],
            "description": "Event bez data.",
        }
        assert _is_complete(event) is False
        assert "date" in _missing_fields(event)

    def test_missing_everything(self):
        event = {}
        assert _is_complete(event) is False
        assert len(_missing_fields(event)) == 4


class TestEnrichEvents:
    @pytest.mark.anyio
    async def test_complete_after_url_fetch(self):
        """When URL fetch + LLM gives complete data, no search is needed."""
        raw = [{"title": "AI Meetup", "url": "https://example.com/ai"}]

        complete_result = {
            "title": "AI Meetup",
            "url": "https://example.com/ai",
            "date": "2026-03-15T18:00:00",
            "location": "Praha",
            "speakers": ["Jan Novák"],
            "description": "Meetup o AI v Praze.",
        }

        with (
            patch("app.event_enricher.rag_search", new_callable=AsyncMock, return_value=[{"markdown": "# AI Meetup content"}]) as mock_rag,
            patch.object(EventEnricher, "_extract_one", new_callable=AsyncMock, return_value=complete_result),
        ):
            enricher = EventEnricher()
            results = await enricher.enrich_events(raw)

        assert len(results) == 1
        assert results[0]["date"] == "2026-03-15T18:00:00"
        assert results[0]["speakers"] == ["Jan Novák"]
        # Only URL fetch, no search
        mock_rag.assert_called_once_with("https://example.com/ai", max_results=1)

    @pytest.mark.anyio
    async def test_search_triggered_when_incomplete(self):
        """When URL fetch gives incomplete data, search is triggered."""
        raw = [{"title": "AI Meetup", "url": "https://example.com/ai", "date_text": "15. března"}]

        incomplete_result = {
            "title": "AI Meetup",
            "url": "https://example.com/ai",
            "date": "2026-03-15T18:00:00",
            "location": "Praha",
            "speakers": [],
            "description": "AI event.",
        }

        complete_result = {
            **incomplete_result,
            "speakers": ["Jan Novák", "Petra Malá"],
        }

        extract_call_count = 0

        async def mock_extract(event):
            nonlocal extract_call_count
            extract_call_count += 1
            if extract_call_count == 1:
                return incomplete_result
            return complete_result

        rag_call_count = 0

        async def mock_rag(query, *, max_results=3):
            nonlocal rag_call_count
            rag_call_count += 1
            if rag_call_count == 1:
                return [{"markdown": "# URL content"}]
            return [{"markdown": "# Search results with speakers"}]

        with (
            patch("app.event_enricher.rag_search", side_effect=mock_rag),
            patch.object(EventEnricher, "_extract_one", side_effect=mock_extract),
        ):
            enricher = EventEnricher()
            results = await enricher.enrich_events(raw)

        assert results[0]["speakers"] == ["Jan Novák", "Petra Malá"]
        assert rag_call_count == 2  # URL fetch + search
        assert extract_call_count == 2  # Two LLM calls

    @pytest.mark.anyio
    async def test_empty_events(self):
        enricher = EventEnricher()
        results = await enricher.enrich_events([])
        assert results == []

    @pytest.mark.anyio
    async def test_402_stops_all_rag(self):
        """402 error stops RAG for all remaining events."""
        raw = [
            {"title": "Event 1", "url": "https://example.com/1"},
            {"title": "Event 2", "url": "https://example.com/2"},
        ]

        response = httpx.Response(402, request=httpx.Request("POST", "https://api.apify.com"))

        fallback_result = {
            "title": "Fallback",
            "date": None,
            "location": None,
            "speakers": [],
            "description": None,
        }

        with (
            patch(
                "app.event_enricher.rag_search",
                new_callable=AsyncMock,
                side_effect=httpx.HTTPStatusError("Payment Required", request=response.request, response=response),
            ),
            patch.object(EventEnricher, "_extract_one", new_callable=AsyncMock, return_value=fallback_result),
        ):
            enricher = EventEnricher()
            results = await enricher.enrich_events(raw)

        assert len(results) == 2

    @pytest.mark.anyio
    async def test_keeps_better_result(self):
        """When search doesn't improve result, keeps original."""
        raw = [{"title": "Event", "url": "https://example.com/1"}]

        result_with_date = {
            "title": "Event",
            "date": "2026-03-15T18:00:00",
            "location": None,
            "speakers": [],
            "description": "Popis.",
        }

        # Search result is equally incomplete
        result_from_search = {
            "title": "Event",
            "date": "2026-03-15T18:00:00",
            "location": None,
            "speakers": [],
            "description": "Jiný popis.",
        }

        extract_count = 0

        async def mock_extract(event):
            nonlocal extract_count
            extract_count += 1
            if extract_count == 1:
                return result_with_date
            return result_from_search

        with (
            patch("app.event_enricher.rag_search", new_callable=AsyncMock, return_value=[{"markdown": "content"}]),
            patch.object(EventEnricher, "_extract_one", side_effect=mock_extract),
        ):
            enricher = EventEnricher()
            results = await enricher.enrich_events(raw)

        # Keeps original since search didn't improve (same number of missing fields)
        assert results[0]["description"] == "Popis."
