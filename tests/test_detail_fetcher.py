from unittest.mock import AsyncMock, patch

import pytest

from app.detail_fetcher import DetailFetcher


class TestFetchDetails:
    @pytest.mark.anyio
    async def test_fetch_details_with_apify_results(self):
        """Events are enriched with markdown from Apify crawl results."""
        events = [
            {"title": "Event 1", "url": "https://example.com/event1"},
            {"title": "Event 2", "url": "https://example.com/event2"},
        ]

        crawl_results = {
            "https://example.com/event1": {"url": "https://example.com/event1", "markdown": "# Event 1\nDetails here"},
            "https://example.com/event2": {"url": "https://example.com/event2", "markdown": "# Event 2\nMore details"},
        }

        with patch("app.detail_fetcher.crawl_urls", new_callable=AsyncMock, return_value=crawl_results):
            fetcher = DetailFetcher()
            results = await fetcher.fetch_details(events)

        assert len(results) == 2
        assert results[0]["markdown"] == "# Event 1\nDetails here"
        assert results[1]["markdown"] == "# Event 2\nMore details"
        assert results[0]["json_ld"] is None
        assert results[0]["og_meta"] == {}

    @pytest.mark.anyio
    async def test_fetch_details_rag_fallback(self):
        """Missing events fall back to RAG search."""
        events = [
            {"title": "Found Event", "url": "https://example.com/found"},
            {"title": "Missing Event", "url": "https://example.com/missing"},
        ]

        crawl_results = {
            "https://example.com/found": {"url": "https://example.com/found", "markdown": "# Found"},
        }

        rag_results = [
            {"markdown": "# Missing Event from RAG\nFound via search"},
        ]

        with (
            patch("app.detail_fetcher.crawl_urls", new_callable=AsyncMock, return_value=crawl_results),
            patch("app.detail_fetcher.rag_search", new_callable=AsyncMock, return_value=rag_results),
        ):
            fetcher = DetailFetcher()
            results = await fetcher.fetch_details(events)

        assert len(results) == 2
        assert results[0]["markdown"] == "# Found"
        assert "Missing Event from RAG" in results[1]["markdown"]

    @pytest.mark.anyio
    async def test_fetch_details_empty_events(self):
        """Empty event list returns empty results."""
        fetcher = DetailFetcher()
        results = await fetcher.fetch_details([])
        assert results == []

    @pytest.mark.anyio
    async def test_fetch_details_all_fail(self):
        """When both Apify methods fail, events get empty markdown."""
        events = [{"title": "Lonely Event", "url": "https://example.com/lonely"}]

        with (
            patch("app.detail_fetcher.crawl_urls", new_callable=AsyncMock, return_value={}),
            patch("app.detail_fetcher.rag_search", new_callable=AsyncMock, return_value=[]),
        ):
            fetcher = DetailFetcher()
            results = await fetcher.fetch_details(events)

        assert len(results) == 1
        assert results[0]["title"] == "Lonely Event"
        assert results[0]["markdown"] == ""

    @pytest.mark.anyio
    async def test_fetch_details_truncates_markdown(self):
        """Markdown is truncated to MARKDOWN_MAX_CHARS."""
        events = [{"title": "Long", "url": "https://example.com/long"}]

        crawl_results = {
            "https://example.com/long": {"url": "https://example.com/long", "markdown": "x" * 5000},
        }

        with patch("app.detail_fetcher.crawl_urls", new_callable=AsyncMock, return_value=crawl_results):
            fetcher = DetailFetcher()
            results = await fetcher.fetch_details(events)

        assert len(results[0]["markdown"]) == 3000

    @pytest.mark.anyio
    async def test_fetch_details_preserves_original_data(self):
        """Original event fields are preserved in enriched output."""
        events = [{"title": "Test", "url": "https://example.com/test", "date_text": "25. března"}]

        crawl_results = {
            "https://example.com/test": {"url": "https://example.com/test", "markdown": "# Test"},
        }

        with patch("app.detail_fetcher.crawl_urls", new_callable=AsyncMock, return_value=crawl_results):
            fetcher = DetailFetcher()
            results = await fetcher.fetch_details(events)

        assert results[0]["title"] == "Test"
        assert results[0]["date_text"] == "25. března"
        assert results[0]["url"] == "https://example.com/test"
