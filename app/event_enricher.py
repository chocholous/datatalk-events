"""Quality-driven event enrichment pipeline.

For each event, iteratively fetches data and runs LLM extraction
until all key fields are filled or all data sources are exhausted.

Flow per event:
1. RAG browser fetch URL → markdown → LLM extract
2. Check completeness (date, speakers, location, description)
3. If incomplete → RAG search → combined markdown → LLM re-extract
4. Return best result
"""

import logging

import httpx

from app.apify_client import rag_search
from app.extractor import EventExtractor

log = logging.getLogger(__name__)

# Fields that define a "complete" event extraction
COMPLETENESS_FIELDS = ["date", "location", "speakers", "description"]


def _is_complete(event: dict) -> bool:
    """Check if LLM extraction found all key fields."""
    if not event.get("date"):
        return False
    if not event.get("location"):
        return False
    if not event.get("description"):
        return False
    speakers = event.get("speakers")
    if not speakers or (isinstance(speakers, list) and len(speakers) == 0):
        return False
    return True


def _missing_fields(event: dict) -> list[str]:
    """Return list of missing key fields for logging."""
    missing = []
    for field in COMPLETENESS_FIELDS:
        value = event.get(field)
        if not value or (isinstance(value, list) and len(value) == 0):
            missing.append(field)
    return missing


class EventEnricher:
    """Quality-driven event enrichment: fetch data + LLM extract in a loop."""

    def __init__(self):
        self.extractor = EventExtractor()

    async def enrich_events(self, events: list[dict]) -> list[dict]:
        """Enrich all events with iterative fetch + extract."""
        results = []
        rag_failed = False

        for event in events:
            result, rag_failed = await self._enrich_one(event, rag_failed)
            results.append(result)

        log.warning("Enrichment complete: %d events", len(results))
        return results

    async def _enrich_one(
        self, event: dict, rag_failed: bool
    ) -> tuple[dict, bool]:
        url = event.get("url", "")
        title = event.get("title", "")

        # Step 1: Fetch URL directly via RAG browser
        markdown = ""
        if not rag_failed and url:
            try:
                markdown = await self._fetch_url(url)
                log.warning("RAG fetch '%s': %d chars", title, len(markdown))
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 402:
                    log.warning("Apify 402 — stopping RAG for remaining events")
                    rag_failed = True

        # Step 2: LLM extraction
        enriched_event = {**event, "markdown": markdown}
        result = await self._extract_one(enriched_event)

        if _is_complete(result):
            log.warning("Event '%s' complete after URL fetch", title)
            return result, rag_failed

        missing = _missing_fields(result)
        log.warning(
            "Event '%s' incomplete after URL fetch, missing: %s",
            title, missing,
        )

        # Step 3: Search for more data
        if not rag_failed:
            try:
                search_markdown = await self._search_event(event)
                if search_markdown:
                    # Combine URL markdown + search markdown
                    combined = markdown
                    if combined:
                        combined += "\n\n--- Additional search results ---\n\n"
                    combined += search_markdown

                    enriched_event["markdown"] = combined
                    result2 = await self._extract_one(enriched_event)

                    if _is_complete(result2):
                        log.warning("Event '%s' complete after search", title)
                        return result2, rag_failed

                    # Use whichever result has more fields filled
                    missing2 = _missing_fields(result2)
                    if len(missing2) < len(missing):
                        log.warning(
                            "Event '%s' improved after search, still missing: %s",
                            title, missing2,
                        )
                        result = result2
                    else:
                        log.warning(
                            "Event '%s' not improved by search, keeping original",
                            title,
                        )
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 402:
                    log.warning("Apify 402 — stopping RAG search")
                    rag_failed = True

        remaining = _missing_fields(result)
        if remaining:
            log.warning(
                "Event '%s' final result still missing: %s", title, remaining
            )

        return result, rag_failed

    async def _extract_one(self, event: dict) -> dict:
        """Run LLM extraction on a single event."""
        results = await self.extractor.extract([event])
        if results:
            return results[0]
        return event

    async def _fetch_url(self, url: str) -> str:
        """Fetch URL directly via RAG browser."""
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
        log.warning(
            "RAG search found content for: %s (%d chars)", title, len(markdown)
        )
        return markdown
