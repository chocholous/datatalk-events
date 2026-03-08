from unittest.mock import AsyncMock, patch

import pytest

from app.scraper import Scraper

# Markdown format from Apify RAG browser
SAMPLE_MARKDOWN = """DATA talk Kalendář

# Kalendář datových akcí

*   **[AI Meetup Prague](https://example.com/event1)** (úterý 15. března, Praha)
*   **[Data Engineering Workshop](https://example.com/event2)** (10. dubna, Brno)
*   **[Machine Learning Prague 2026](https://www.mlprague.com/)** (4.–6. května, Praha)
"""

SAMPLE_MARKDOWN_EMPTY = """DATA talk Kalendář

# Kalendář datových akcí

No events found.
"""


class TestParseEvents:
    def test_parse_events_from_markdown(self):
        scraper = Scraper()
        events = scraper.parse_events(SAMPLE_MARKDOWN)

        assert len(events) == 3

        assert events[0]["title"] == "AI Meetup Prague"
        assert events[0]["url"] == "https://example.com/event1"
        assert events[0]["date_text"] == "úterý 15. března, Praha"
        assert "AI Meetup Prague" in events[0]["description"]

        assert events[1]["title"] == "Data Engineering Workshop"
        assert events[1]["url"] == "https://example.com/event2"
        assert events[1]["date_text"] == "10. dubna, Brno"

        assert events[2]["title"] == "Machine Learning Prague 2026"
        assert events[2]["url"] == "https://www.mlprague.com/"

    def test_parse_events_empty_markdown(self):
        scraper = Scraper()
        events = scraper.parse_events(SAMPLE_MARKDOWN_EMPTY)
        assert events == []

    def test_parse_events_empty_string(self):
        scraper = Scraper()
        events = scraper.parse_events("")
        assert events == []


class TestScrape:
    @pytest.mark.anyio
    async def test_scrape_calls_rag_search(self):
        rag_results = [{"markdown": SAMPLE_MARKDOWN}]

        with patch("app.scraper.rag_search", new_callable=AsyncMock, return_value=rag_results):
            scraper = Scraper()
            events = await scraper.scrape()

        assert len(events) == 3
        assert events[0]["title"] == "AI Meetup Prague"

    @pytest.mark.anyio
    async def test_scrape_returns_empty_on_failure(self):
        with patch("app.scraper.rag_search", new_callable=AsyncMock, return_value=[]):
            scraper = Scraper()
            events = await scraper.scrape()

        assert events == []
