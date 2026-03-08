import logging

from app.apify_client import crawl_urls, rag_search

log = logging.getLogger(__name__)

MARKDOWN_MAX_CHARS = 3000


class DetailFetcher:
    """Fetch event detail pages using Apify.

    Primary: Apify Website Content Crawler (batch, Playwright + residential proxy).
    Fallback: Apify RAG Web Browser (search by event title).
    """

    async def fetch_details(self, events: list[dict]) -> list[dict]:
        """Fetch detail pages for all events.

        Returns enriched event dicts with 'markdown' key.
        """
        if not events:
            return []

        urls = [e.get("url", "") for e in events if e.get("url")]

        # 1. Batch crawl all URLs via Apify Website Content Crawler
        crawl_results = await crawl_urls(urls)

        # 2. Enrich events with results, collect missing ones
        enriched = []
        missing = []
        for event in events:
            url = event.get("url", "")
            result = crawl_results.get(url)
            if result and result.get("markdown", "").strip():
                enriched.append(
                    {
                        **event,
                        "json_ld": None,
                        "og_meta": {},
                        "markdown": result["markdown"][:MARKDOWN_MAX_CHARS],
                    }
                )
            else:
                missing.append(event)

        # 3. Fallback: RAG search for events that weren't crawled
        for event in missing:
            title = event.get("title", "")
            log.info("Crawl missed %s, trying RAG search: %s", event.get("url"), title)
            markdown = await self._rag_fallback(title)
            enriched.append(
                {
                    **event,
                    "json_ld": None,
                    "og_meta": {},
                    "markdown": markdown,
                }
            )

        return enriched

    async def _rag_fallback(self, title: str) -> str:
        """Search for event by title using Apify RAG Web Browser."""
        if not title:
            return ""

        results = await rag_search(f"{title} event", max_results=3)
        if not results:
            log.warning("RAG search found nothing for: %s", title)
            return ""

        # Pick the result with the most content
        best = max(results, key=lambda r: len(r.get("markdown", "")))
        markdown = best.get("markdown", "")
        log.info("RAG search found content for: %s (%d chars)", title, len(markdown))
        return markdown[:MARKDOWN_MAX_CHARS]
