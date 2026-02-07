import httpx
import pytest
from bs4 import BeautifulSoup

from app.detail_fetcher import DetailFetcher

# ── HTML fixtures ────────────────────────────────────────────────────────

HTML_JSON_LD_EVENT = """
<html><head>
<script type="application/ld+json">
{"@type": "Event", "name": "AI Meetup", "startDate": "2025-06-01"}
</script>
</head><body><main><p>Hello world</p></main></body></html>
"""

HTML_JSON_LD_GRAPH = """
<html><head>
<script type="application/ld+json">
{"@context": "https://schema.org", "@graph": [
  {"@type": "WebPage", "name": "Page"},
  {"@type": "Event", "name": "Data Workshop", "location": "Prague"}
]}
</script>
</head><body><main><p>Content</p></main></body></html>
"""

HTML_NO_JSON_LD = """
<html><head><title>No LD</title></head>
<body><main><p>Plain page</p></main></body></html>
"""

HTML_OG_META = """
<html><head>
<meta property="og:title" content="Test Event">
<meta property="og:description" content="A great event">
<meta property="og:image" content="https://example.com/img.jpg">
</head><body><main><p>Content</p></main></body></html>
"""

HTML_NO_OG = """
<html><head><meta charset="utf-8"></head>
<body><main><p>No OG</p></main></body></html>
"""

HTML_FULL_PAGE = """
<html><body>
<nav><a href="/">Home</a></nav>
<main>
<h1>Event Title</h1>
<p>This is the event description with some details.</p>
</main>
<footer>Copyright 2025</footer>
</body></html>
"""


# ── JSON-LD tests ────────────────────────────────────────────────────────


class TestExtractJsonLd:
    def test_extract_json_ld_event(self):
        fetcher = DetailFetcher()
        soup = BeautifulSoup(HTML_JSON_LD_EVENT, "html.parser")
        result = fetcher._extract_json_ld(soup)
        assert result is not None
        assert result["@type"] == "Event"
        assert result["name"] == "AI Meetup"

    def test_extract_json_ld_graph(self):
        fetcher = DetailFetcher()
        soup = BeautifulSoup(HTML_JSON_LD_GRAPH, "html.parser")
        result = fetcher._extract_json_ld(soup)
        assert result is not None
        assert result["@type"] == "Event"
        assert result["name"] == "Data Workshop"

    def test_extract_json_ld_missing(self):
        fetcher = DetailFetcher()
        soup = BeautifulSoup(HTML_NO_JSON_LD, "html.parser")
        result = fetcher._extract_json_ld(soup)
        assert result is None


# ── OpenGraph tests ──────────────────────────────────────────────────────


class TestExtractOgMeta:
    def test_extract_og_meta(self):
        fetcher = DetailFetcher()
        soup = BeautifulSoup(HTML_OG_META, "html.parser")
        result = fetcher._extract_og_meta(soup)
        assert result["og:title"] == "Test Event"
        assert result["og:description"] == "A great event"
        assert result["og:image"] == "https://example.com/img.jpg"

    def test_extract_og_meta_missing(self):
        fetcher = DetailFetcher()
        soup = BeautifulSoup(HTML_NO_OG, "html.parser")
        result = fetcher._extract_og_meta(soup)
        assert result == {}


# ── Markdown conversion tests ────────────────────────────────────────────


class TestHtmlToMarkdown:
    def test_html_to_markdown(self):
        fetcher = DetailFetcher()
        soup = BeautifulSoup(HTML_FULL_PAGE, "html.parser")
        result = fetcher._html_to_markdown(soup)
        assert "Event Title" in result
        assert "event description" in result
        # Truncation: result should be <= 3000 chars
        assert len(result) <= 3000

    def test_html_to_markdown_strips_nav_footer(self):
        fetcher = DetailFetcher()
        soup = BeautifulSoup(HTML_FULL_PAGE, "html.parser")
        result = fetcher._html_to_markdown(soup)
        assert "Home" not in result  # nav removed
        assert "Copyright" not in result  # footer removed

    def test_html_to_markdown_truncates_long_content(self):
        long_html = (
            "<html><body><main>"
            + "<p>" + "x" * 5000 + "</p>"
            + "</main></body></html>"
        )
        fetcher = DetailFetcher()
        soup = BeautifulSoup(long_html, "html.parser")
        result = fetcher._html_to_markdown(soup)
        assert len(result) <= 3000


# ── Concurrent fetch tests ──────────────────────────────────────────────


class TestFetchDetails:
    @pytest.mark.anyio
    async def test_fetch_details_concurrent(self, respx_mock, monkeypatch):
        monkeypatch.setenv("SCRAPE_DETAIL_CONCURRENCY", "2")
        monkeypatch.setenv("SCRAPE_DETAIL_TIMEOUT", "5")
        from app.config import get_settings
        get_settings.cache_clear()

        url1 = "https://example.com/event1"
        url2 = "https://example.com/event2"

        respx_mock.get(url1).mock(return_value=httpx.Response(200, text=HTML_JSON_LD_EVENT))
        respx_mock.get(url2).mock(return_value=httpx.Response(200, text=HTML_OG_META))

        events = [
            {"title": "Event 1", "url": url1},
            {"title": "Event 2", "url": url2},
        ]

        fetcher = DetailFetcher()
        results = await fetcher.fetch_details(events)

        assert len(results) == 2

        # Event 1 has JSON-LD
        assert results[0]["title"] == "Event 1"
        assert results[0]["json_ld"] is not None
        assert results[0]["json_ld"]["name"] == "AI Meetup"

        # Event 2 has OG meta
        assert results[1]["title"] == "Event 2"
        assert results[1]["og_meta"]["og:title"] == "Test Event"

        # Both have markdown
        assert isinstance(results[0]["markdown"], str)
        assert isinstance(results[1]["markdown"], str)

        get_settings.cache_clear()

    @pytest.mark.anyio
    async def test_fetch_details_single_failure(self, respx_mock, monkeypatch):
        monkeypatch.setenv("SCRAPE_DETAIL_CONCURRENCY", "2")
        monkeypatch.setenv("SCRAPE_DETAIL_TIMEOUT", "5")
        from app.config import get_settings
        get_settings.cache_clear()

        url_ok = "https://example.com/ok"
        url_fail = "https://example.com/fail"

        respx_mock.get(url_ok).mock(return_value=httpx.Response(200, text=HTML_OG_META))
        respx_mock.get(url_fail).mock(return_value=httpx.Response(500))

        events = [
            {"title": "OK Event", "url": url_ok},
            {"title": "Fail Event", "url": url_fail},
        ]

        fetcher = DetailFetcher()
        results = await fetcher.fetch_details(events)

        assert len(results) == 2

        # OK event has data
        assert results[0]["og_meta"]["og:title"] == "Test Event"

        # Failed event has empty defaults
        assert results[1]["json_ld"] is None
        assert results[1]["og_meta"] == {}
        assert results[1]["markdown"] == ""
        # Original data preserved
        assert results[1]["title"] == "Fail Event"

        get_settings.cache_clear()
