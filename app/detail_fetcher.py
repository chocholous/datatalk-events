import asyncio
import json
import logging

import httpx
from bs4 import BeautifulSoup
from markdownify import markdownify

from app.config import get_settings

log = logging.getLogger(__name__)

MARKDOWN_MAX_CHARS = 3000

# Domains known to block scrapers
BLOCKED_DOMAINS = {"linkedin.com", "www.linkedin.com"}

# Signals that a page is a login/block page rather than real content
BLOCKED_TITLE_KEYWORDS = ["login", "sign in", "log in", "přihlásit", "captcha", "verify"]


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

        # Detect blocked/login pages and try web search fallback
        if self._is_blocked(soup, url):
            title = event.get("title", "")
            log.info("Page blocked (%s), searching for: %s", url, title)
            fallback_soup = await self._search_fallback(title, url, sem, client)
            if fallback_soup:
                soup = fallback_soup

        enriched["json_ld"] = self._extract_json_ld(soup)
        enriched["og_meta"] = self._extract_og_meta(soup)
        enriched["markdown"] = self._html_to_markdown(soup)
        return enriched

    def _is_blocked(self, soup: BeautifulSoup, url: str) -> bool:
        """Detect if a page is a login/captcha wall instead of real content."""
        from urllib.parse import urlparse

        # Known blocked domains
        domain = urlparse(url).netloc.lower()
        if any(domain.endswith(bd) for bd in BLOCKED_DOMAINS):
            return True

        # Check page title for block signals
        title_tag = soup.find("title")
        if title_tag:
            title_text = title_tag.get_text().lower()
            if any(kw in title_text for kw in BLOCKED_TITLE_KEYWORDS):
                return True

        # No JSON-LD Event data + very short body = likely blocked
        has_json_ld = self._extract_json_ld(soup) is not None
        body = soup.find("body")
        body_text_len = len(body.get_text(strip=True)) if body else 0
        if not has_json_ld and body_text_len < 200:
            return True

        return False

    async def _search_fallback(
        self,
        title: str,
        original_url: str,
        sem: asyncio.Semaphore,
        client: httpx.AsyncClient,
    ) -> BeautifulSoup | None:
        """Search for event by title and scrape an alternative page."""
        try:
            from ddgs import DDGS
            from urllib.parse import urlparse

            original_domain = urlparse(original_url).netloc.lower()

            with DDGS() as ddgs:
                results = list(ddgs.text(f"{title} event", max_results=5))

            for result in results:
                alt_url = result.get("href", "")
                alt_domain = urlparse(alt_url).netloc.lower()

                # Skip same blocked domain
                if alt_domain == original_domain:
                    continue
                if any(alt_domain.endswith(bd) for bd in BLOCKED_DOMAINS):
                    continue

                log.info("Trying fallback URL: %s", alt_url)
                try:
                    async with sem:
                        resp = await client.get(alt_url)
                        resp.raise_for_status()
                    alt_soup = BeautifulSoup(resp.text, "html.parser")
                    # Verify it's not also blocked
                    if not self._is_blocked(alt_soup, alt_url):
                        log.info("Fallback success: %s", alt_url)
                        return alt_soup
                except Exception:
                    log.debug("Fallback URL failed: %s", alt_url, exc_info=True)
                    continue

            log.warning("No fallback found for: %s", title)
        except Exception:
            log.warning("Search fallback failed for: %s", title, exc_info=True)
        return None

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
