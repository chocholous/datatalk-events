import httpx
import pytest

from app.scraper import Scraper

SAMPLE_HTML = """
<html>
<body>
<article>
    <h2><a href="/event/ai-meetup">AI Meetup Prague</a></h2>
    <time>2025-03-15</time>
    <p>Join us for an evening of AI talks and networking.</p>
</article>
<article>
    <h3><a href="https://example.com/event2">Data Engineering Workshop</a></h3>
    <span class="date">April 10, 2025</span>
    <p>Hands-on workshop on modern data pipelines.</p>
</article>
<article>
    <span>No title link here</span>
</article>
</body>
</html>
"""


class TestParseEvents:
    def test_parse_events_from_html(self):
        scraper = Scraper()
        events = scraper.parse_events(SAMPLE_HTML)

        assert len(events) == 2

        assert events[0]["title"] == "AI Meetup Prague"
        assert events[0]["url"] == "https://datatalk.cz/event/ai-meetup"
        assert events[0]["date_text"] == "2025-03-15"
        assert "AI talks" in events[0]["description"]

        assert events[1]["title"] == "Data Engineering Workshop"
        assert events[1]["url"] == "https://example.com/event2"
        assert events[1]["date_text"] == "April 10, 2025"
        assert "data pipelines" in events[1]["description"]

    def test_parse_events_empty_html(self):
        scraper = Scraper()
        events = scraper.parse_events("<html><body></body></html>")
        assert events == []


class TestFetchPage:
    @pytest.mark.anyio
    async def test_fetch_page_retries_on_500(self, respx_mock):
        """Mock httpx to fail twice with 500, then succeed on third attempt."""
        url = "https://example.com/events"

        route = respx_mock.get(url)
        route.side_effect = [
            httpx.Response(500),
            httpx.Response(500),
            httpx.Response(200, text="<html>OK</html>"),
        ]

        scraper = Scraper()
        result = await scraper.fetch_page(url)

        assert result == "<html>OK</html>"
        assert route.call_count == 3
