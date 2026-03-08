import logging

import httpx

from app.apify_client import rag_search

log = logging.getLogger(__name__)

# Minimum markdown length to consider data "complete" from URL fetch
MIN_COMPLETE_LENGTH = 500


class DetailFetcher:
    """Fetch event detail pages using Apify RAG Web Browser.

    Quality-driven strategy:
    1. Fetch event URL directly via RAG browser
    2. If data is incomplete (too short), search for more info
    3. Use the better result
    """

    async def fetch_details(self, events: list[dict]) -> list[dict]:
        """Fetch detail pages for all events."""
        if not events:
            return []

        enriched = []
        rag_failed = False

        for event in events:
            url = event.get("url", "")
            title = event.get("title", "")
            markdown = ""

            # Step 1: Fetch URL directly via RAG browser
            if not rag_failed and url:
                try:
                    markdown = await self._fetch_url(url)
                    log.warning(
                        "RAG fetch for '%s': %d chars", title, len(markdown)
                    )
                except httpx.HTTPStatusError as exc:
                    if exc.response.status_code == 402:
                        log.warning("Apify 402 — stopping RAG for remaining events")
                        rag_failed = True

            # Step 2: If incomplete, try search to find more data
            if not rag_failed and len(markdown) < MIN_COMPLETE_LENGTH:
                log.warning(
                    "URL fetch incomplete for '%s' (%d chars), trying search",
                    title, len(markdown),
                )
                try:
                    search_markdown = await self._search_event(event)
                    if len(search_markdown) > len(markdown):
                        log.warning(
                            "Search found better data for '%s': %d chars",
                            title, len(search_markdown),
                        )
                        markdown = search_markdown
                except httpx.HTTPStatusError as exc:
                    if exc.response.status_code == 402:
                        log.warning("Apify 402 — stopping RAG search")
                        rag_failed = True

            enriched.append({**event, "markdown": markdown})

        return enriched

    async def _fetch_url(self, url: str) -> str:
        """Fetch a URL directly via RAG browser."""
        results = await rag_search(url, max_results=1)
        if not results:
            return ""
        return results[0].get("markdown", "")

    async def _search_event(self, event: dict) -> str:
        """Search for event info using all available data."""
        title = event.get("title", "")
        url = event.get("url", "")
        date_text = event.get("date_text", "")

        if not title and not url:
            return ""

        query_parts = [title, date_text, url]
        query = " ".join(p for p in query_parts if p)

        results = await rag_search(query, max_results=3)
        if not results:
            log.warning("RAG search found nothing for: %s", title)
            return ""

        best = max(results, key=lambda r: len(r.get("markdown", "")))
        markdown = best.get("markdown", "")
        log.warning("RAG search found content for: %s (%d chars)", title, len(markdown))
        return markdown
