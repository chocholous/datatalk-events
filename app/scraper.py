import logging
import re

from app.apify_client import rag_search
from app.config import get_settings

log = logging.getLogger(__name__)

# Pattern: **[Title](URL)** (date_text)
_EVENT_RE = re.compile(
    r"\*\*\[(.+?)\]\((https?://[^\)]+)\)\*\*\s*\(([^)]+)\)"
)


class Scraper:
    """Scrape events from DataTalk.cz using Apify RAG Web Browser."""

    def parse_events(self, markdown: str) -> list[dict]:
        """Parse event entries from markdown returned by RAG browser.

        Expected format per line:
        **[Event Title](https://example.com/event)** (date, location)
        """
        events = []
        for match in _EVENT_RE.finditer(markdown):
            title, url, date_text = match.groups()
            events.append(
                {
                    "title": title.strip(),
                    "url": url.strip(),
                    "date_text": date_text.strip(),
                    "description": f"{title} ({date_text})",
                }
            )
        return events

    async def scrape(self) -> list[dict]:
        settings = get_settings()
        log.warning("Scraping %s via Apify RAG browser", settings.scrape_url)

        results = await rag_search(settings.scrape_url, max_results=1)
        if not results:
            log.warning("Apify RAG browser returned no results")
            return []

        markdown = results[0].get("markdown", "")
        log.warning("RAG browser returned %d chars of markdown", len(markdown))
        events = self.parse_events(markdown)
        log.warning("Parsed %d events from markdown", len(events))
        return events
