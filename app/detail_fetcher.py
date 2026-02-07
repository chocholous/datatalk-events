import asyncio
import json
import logging

import httpx
from bs4 import BeautifulSoup
from markdownify import markdownify

from app.config import get_settings

log = logging.getLogger(__name__)

MARKDOWN_MAX_CHARS = 3000


class DetailFetcher:
    """Fetch event detail pages and extract structured data."""

    async def fetch_details(self, events: list[dict]) -> list[dict]:
        """Concurrently fetch detail pages for all events.

        For each event, fetches the URL, extracts:
        - json_ld: parsed JSON-LD data (dict or None)
        - og_meta: OpenGraph meta tags (dict)
        - markdown: HTML body converted to markdown (truncated)

        Returns enriched event dicts with these new keys.
        """
        settings = get_settings()
        sem = asyncio.Semaphore(settings.scrape_detail_concurrency)
        async with httpx.AsyncClient(
            timeout=settings.scrape_detail_timeout, follow_redirects=True
        ) as client:
            tasks = [self._fetch_single(event, sem, client) for event in events]
            return await asyncio.gather(*tasks)

    async def _fetch_single(
        self, event: dict, sem: asyncio.Semaphore, client: httpx.AsyncClient
    ) -> dict:
        """Fetch and parse a single event detail page."""
        enriched = {**event, "json_ld": None, "og_meta": {}, "markdown": ""}
        url = event.get("url", "")
        if not url:
            return enriched

        try:
            async with sem:
                response = await client.get(url)
                response.raise_for_status()
        except Exception:
            log.warning("Failed to fetch detail page: %s", url, exc_info=True)
            return enriched

        soup = BeautifulSoup(response.text, "html.parser")
        enriched["json_ld"] = self._extract_json_ld(soup)
        enriched["og_meta"] = self._extract_og_meta(soup)
        enriched["markdown"] = self._html_to_markdown(soup)
        return enriched

    def _extract_json_ld(self, soup: BeautifulSoup) -> dict | None:
        """Extract first Event-type JSON-LD from <script type='application/ld+json'>."""
        for script in soup.select('script[type="application/ld+json"]'):
            try:
                data = json.loads(script.string or "")
            except (json.JSONDecodeError, TypeError):
                continue

            # Direct Event object
            if isinstance(data, dict) and data.get("@type") == "Event":
                return data

            # @graph array
            if isinstance(data, dict) and "@graph" in data:
                for item in data["@graph"]:
                    if isinstance(item, dict) and item.get("@type") == "Event":
                        return item

            # Top-level array
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, dict) and item.get("@type") == "Event":
                        return item

        return None

    def _extract_og_meta(self, soup: BeautifulSoup) -> dict:
        """Extract OpenGraph meta tags (og:title, og:description, og:image, etc.)."""
        result = {}
        for meta in soup.select('meta[property^="og:"]'):
            prop = meta.get("property", "")
            content = meta.get("content", "")
            if prop and content:
                result[prop] = content
        return result

    def _html_to_markdown(self, soup: BeautifulSoup) -> str:
        """Convert page body to markdown via markdownify, truncate to max_chars."""
        # Find main content element
        content_el = (
            soup.find("main") or soup.find("article") or soup.find("body")
        )
        if not content_el:
            return ""

        # Remove noise elements
        for tag_name in ("nav", "footer", "header", "script", "style"):
            for tag in content_el.find_all(tag_name):
                tag.decompose()

        md = markdownify(str(content_el))
        return md[:MARKDOWN_MAX_CHARS]
