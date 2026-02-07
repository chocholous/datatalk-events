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
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            response = await client.get(url)
            response.raise_for_status()
            return response.text

    def parse_events(self, html: str) -> list[dict]:
        """Parse event entries from HTML.

        datatalk.cz/kalendar-akci/ uses <li> elements with <strong><a> for
        event titles and date/location in parentheses after the link.
        Falls back to generic card-based selectors for resilience.
        """
        soup = BeautifulSoup(html, "html.parser")
        events = []

        # Primary: <li> entries with <strong><a href="...">Title</a></strong>
        for li in soup.select("li"):
            strong = li.find("strong")
            if not strong:
                continue
            link_el = strong.find("a", href=True)
            if not link_el:
                continue

            url = link_el.get("href", "")
            title = link_el.get_text(strip=True)

            # Skip navigation links (relative paths to site sections)
            if not title or (url.startswith("/") and not url.startswith("//")):
                continue

            if url and not url.startswith("http"):
                url = f"https://datatalk.cz{url}"

            # Extract date/location from parenthesized text after the link
            full_text = li.get_text(strip=True)
            date_text = None
            # Pattern: "Title(date, location)" — extract what's in parens
            paren_start = full_text.find("(")
            paren_end = full_text.find(")")
            if paren_start != -1 and paren_end != -1:
                date_text = full_text[paren_start + 1:paren_end]

            events.append(
                {
                    "title": title,
                    "url": url,
                    "date_text": date_text,
                    "description": full_text[:500],
                }
            )

        if events:
            return events

        # Fallback: generic card-based selectors
        for card in soup.select(
            ".event-card, .event-item, article, "
            ".tribe-events-calendar-list__event"
        ):
            title_el = card.select_one(
                "h2, h3, .tribe-events-calendar-list__event-title, .title"
            )
            link_el = card.select_one("a[href]")
            if title_el and link_el:
                url = link_el.get("href", "")
                if url and not url.startswith("http"):
                    url = f"https://datatalk.cz{url}"
                events.append(
                    {
                        "title": title_el.get_text(strip=True),
                        "url": url,
                        "date_text": None,
                        "description": card.get_text(strip=True)[:500],
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
