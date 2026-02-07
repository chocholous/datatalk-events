import httpx
import pytest

from app.scraper import Scraper

# Primary format: datatalk.cz <li><strong><a> structure
SAMPLE_HTML_PRIMARY = """
<html>
<body>
<ul>
<li><strong><a href="https://example.com/event1">AI Meetup Prague</a></strong>(úterý 15. března, Praha)</li>
<li><strong><a href="https://example.com/event2">Data Engineering Workshop</a></strong>(10. dubna, Brno)</li>
<li><a href="/about">About us</a></li>
</ul>
</body>
</html>
"""

# Fallback format: generic article cards
SAMPLE_HTML_FALLBACK = """
<html>
<body>
<article>
    <h2><a href="https://example.com/evt1">Fallback Event</a></h2>
    <p>Some description.</p>
</article>
</body>
</html>
"""


class TestParseEvents:
    def test_parse_events_primary_format(self):
        scraper = Scraper()
        events = scraper.parse_events(SAMPLE_HTML_PRIMARY)

        assert len(events) == 2

        assert events[0]["title"] == "AI Meetup Prague"
        assert events[0]["url"] == "https://example.com/event1"
        assert events[0]["date_text"] == "úterý 15. března, Praha"
        assert "AI Meetup Prague" in events[0]["description"]

        assert events[1]["title"] == "Data Engineering Workshop"
        assert events[1]["url"] == "https://example.com/event2"
        assert events[1]["date_text"] == "10. dubna, Brno"

    def test_parse_events_fallback_format(self):
        scraper = Scraper()
        events = scraper.parse_events(SAMPLE_HTML_FALLBACK)

        assert len(events) == 1
        assert events[0]["title"] == "Fallback Event"
        assert events[0]["url"] == "https://example.com/evt1"

    def test_parse_events_empty_html(self):
        scraper = Scraper()
        events = scraper.parse_events("<html><body></body></html>")
        assert events == []

    def test_parse_events_skips_relative_navigation_links(self):
        html = """
        <html><body>
        <ul>
        <li><strong><a href="/about">About</a></strong></li>
        <li><strong><a href="https://example.com/real">Real Event</a></strong>(date, place)</li>
        </ul>
        </body></html>
        """
        scraper = Scraper()
        events = scraper.parse_events(html)
        assert len(events) == 1
        assert events[0]["title"] == "Real Event"


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
