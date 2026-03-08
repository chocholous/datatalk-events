from unittest.mock import AsyncMock, patch

import pytest

from app.detail_fetcher import DetailFetcher, MIN_COMPLETE_LENGTH


class TestFetchDetails:
    @pytest.mark.anyio
    async def test_fetch_url_returns_complete_data(self):
        """When URL fetch returns enough data, no search is needed."""
        events = [
            {"title": "Event 1", "url": "https://example.com/event1"},
        ]

        long_markdown = "x" * (MIN_COMPLETE_LENGTH + 100)
        rag_results = [{"markdown": long_markdown}]

        with patch("app.detail_fetcher.rag_search", new_callable=AsyncMock, return_value=rag_results) as mock_rag:
            fetcher = DetailFetcher()
            results = await fetcher.fetch_details(events)

        assert len(results) == 1
        assert results[0]["markdown"] == long_markdown
        # Only one call (URL fetch), no search needed
        mock_rag.assert_called_once_with("https://example.com/event1", max_results=1)

    @pytest.mark.anyio
    async def test_incomplete_url_triggers_search(self):
        """When URL fetch returns too little data, search is tried."""
        events = [
            {"title": "Event 1", "url": "https://example.com/event1", "date_text": "25. března"},
        ]

        short_markdown = "x" * 100
        search_markdown = "y" * (MIN_COMPLETE_LENGTH + 100)

        call_count = 0

        async def mock_rag(query, *, max_results=3):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # URL fetch returns short content
                return [{"markdown": short_markdown}]
            else:
                # Search returns better content
                return [{"markdown": search_markdown}]

        with patch("app.detail_fetcher.rag_search", side_effect=mock_rag):
            fetcher = DetailFetcher()
            results = await fetcher.fetch_details(events)

        assert len(results) == 1
        assert results[0]["markdown"] == search_markdown
        assert call_count == 2

    @pytest.mark.anyio
    async def test_empty_events(self):
        """Empty event list returns empty results."""
        fetcher = DetailFetcher()
        results = await fetcher.fetch_details([])
        assert results == []

    @pytest.mark.anyio
    async def test_both_fail_returns_empty_markdown(self):
        """When both URL fetch and search fail, event gets empty markdown."""
        events = [{"title": "Lonely Event", "url": "https://example.com/lonely"}]

        with patch("app.detail_fetcher.rag_search", new_callable=AsyncMock, return_value=[]):
            fetcher = DetailFetcher()
            results = await fetcher.fetch_details(events)

        assert len(results) == 1
        assert results[0]["title"] == "Lonely Event"
        assert results[0]["markdown"] == ""

    @pytest.mark.anyio
    async def test_no_truncation(self):
        """Markdown is NOT truncated regardless of length."""
        events = [{"title": "Long", "url": "https://example.com/long"}]

        long_markdown = "x" * 50000
        rag_results = [{"markdown": long_markdown}]

        with patch("app.detail_fetcher.rag_search", new_callable=AsyncMock, return_value=rag_results):
            fetcher = DetailFetcher()
            results = await fetcher.fetch_details(events)

        assert len(results[0]["markdown"]) == 50000

    @pytest.mark.anyio
    async def test_preserves_original_data(self):
        """Original event fields are preserved in enriched output."""
        events = [{"title": "Test", "url": "https://example.com/test", "date_text": "25. března"}]

        rag_results = [{"markdown": "x" * (MIN_COMPLETE_LENGTH + 1)}]

        with patch("app.detail_fetcher.rag_search", new_callable=AsyncMock, return_value=rag_results):
            fetcher = DetailFetcher()
            results = await fetcher.fetch_details(events)

        assert results[0]["title"] == "Test"
        assert results[0]["date_text"] == "25. března"
        assert results[0]["url"] == "https://example.com/test"

    @pytest.mark.anyio
    async def test_402_stops_processing(self):
        """402 error stops RAG calls for remaining events."""
        import httpx

        events = [
            {"title": "Event 1", "url": "https://example.com/1"},
            {"title": "Event 2", "url": "https://example.com/2"},
        ]

        response = httpx.Response(402, request=httpx.Request("POST", "https://api.apify.com"))

        with patch(
            "app.detail_fetcher.rag_search",
            new_callable=AsyncMock,
            side_effect=httpx.HTTPStatusError("Payment Required", request=response.request, response=response),
        ):
            fetcher = DetailFetcher()
            results = await fetcher.fetch_details(events)

        assert len(results) == 2
        assert results[0]["markdown"] == ""
        assert results[1]["markdown"] == ""
