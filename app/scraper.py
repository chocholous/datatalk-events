import logging

import httpx
from bs4 import BeautifulSoup
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import get_settings

log = logging.getLogger(__name__)


class Scraper:
    """Scrape events from DataTalk.cz"""

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    async def fetch_page(self, url: str) -> str:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(url)
            response.raise_for_status()
            return response.text

    def parse_events(self, html: str) -> list[dict]:
        """Parse event cards from HTML. Selectors based on datatalk.cz structure."""
        soup = BeautifulSoup(html, "html.parser")
        events = []
        # Try multiple selectors for resilience
        for card in soup.select(
            ".event-card, .event-item, article, "
            ".tribe-events-calendar-list__event"
        ):
            title_el = card.select_one(
                "h2, h3, .tribe-events-calendar-list__event-title, .title"
            )
            link_el = card.select_one("a[href]")
            date_el = card.select_one(
                ".date, time, .tribe-events-calendar-list__event-datetime"
            )
            desc_el = card.select_one(
                ".description, "
                ".tribe-events-calendar-list__event-description, p"
            )

            if title_el and link_el:
                url = link_el.get("href", "")
                if url and not url.startswith("http"):
                    url = f"https://datatalk.cz{url}"
                events.append(
                    {
                        "title": title_el.get_text(strip=True),
                        "url": url,
                        "date_text": (
                            date_el.get_text(strip=True) if date_el else None
                        ),
                        "description": (
                            desc_el.get_text(strip=True)[:500]
                            if desc_el
                            else card.get_text(strip=True)[:500]
                        ),
                    }
                )
        return events

    async def scrape(self) -> list[dict]:
        settings = get_settings()
        log.info(f"Scraping {settings.scrape_url}")
        html = await self.fetch_page(settings.scrape_url)
        events = self.parse_events(html)
        log.info(f"Found {len(events)} events")
        return events
