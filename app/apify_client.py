"""Apify REST API client for running Actors."""

import logging
from urllib.parse import urlparse

import httpx

from app.config import get_settings

log = logging.getLogger(__name__)

APIFY_API_BASE = "https://api.apify.com/v2"


def _normalize_url(url: str) -> str:
    """Normalize URL for matching (strip www., trailing slash, force lowercase)."""
    parsed = urlparse(url)
    host = parsed.netloc.lower().removeprefix("www.")
    path = parsed.path.rstrip("/")
    return f"{parsed.scheme}://{host}{path}"


async def _get_dataset_items(
    client: httpx.AsyncClient, dataset_id: str, token: str, *, limit: int = 100
) -> list[dict]:
    """Fetch items from an Apify dataset."""
    resp = await client.get(
        f"{APIFY_API_BASE}/datasets/{dataset_id}/items",
        params={"token": token, "limit": limit},
    )
    resp.raise_for_status()
    return resp.json()


CRAWL_BATCH_SIZE = 4


async def crawl_urls(
    urls: list[str], *, timeout: int = 300, use_residential_proxy: bool = True
) -> dict[str, dict]:
    """Batch-crawl URLs using Apify Website Content Crawler with Playwright.

    Splits URLs into batches to avoid Apify memory limits.
    Returns a dict mapping original URL -> result item.
    """
    settings = get_settings()
    if not settings.apify_api_token or not urls:
        return {}

    all_results: dict[str, dict] = {}

    for i in range(0, len(urls), CRAWL_BATCH_SIZE):
        batch = urls[i : i + CRAWL_BATCH_SIZE]
        log.warning("Crawling batch %d-%d of %d URLs", i + 1, i + len(batch), len(urls))
        batch_results = await _crawl_batch(batch, timeout=timeout, use_residential_proxy=use_residential_proxy)
        all_results.update(batch_results)

    log.warning("Apify crawled total: matched %d/%d input URLs", len(all_results), len(urls))
    return all_results


async def _crawl_batch(
    urls: list[str], *, timeout: int = 300, use_residential_proxy: bool = True
) -> dict[str, dict]:
    """Crawl a single batch of URLs."""
    settings = get_settings()

    actor_id = "apify~website-content-crawler"
    api_url = f"{APIFY_API_BASE}/acts/{actor_id}/runs"

    input_data = {
        "startUrls": [{"url": url} for url in urls],
        "crawlerType": "playwright:adaptive",
        "maxCrawlDepth": 0,
        "maxCrawlPages": len(urls),
        "maxResults": len(urls),
        "saveMarkdown": True,
        "dynamicContentWaitSecs": 15,
    }

    if use_residential_proxy:
        input_data["proxyConfiguration"] = {
            "useApifyProxy": True,
            "apifyProxyGroups": ["RESIDENTIAL"],
        }

    try:
        async with httpx.AsyncClient(timeout=timeout + 60) as client:
            resp = await client.post(
                api_url,
                params={
                    "token": settings.apify_api_token,
                    "waitForFinish": timeout,
                },
                json=input_data,
            )
            resp.raise_for_status()
            run_data = resp.json().get("data", resp.json())

            run_status = run_data.get("status", "UNKNOWN")
            run_id = run_data.get("id", "?")
            log.warning(
                "Apify run %s finished with status: %s",
                run_id, run_status,
            )
            if run_status not in ("SUCCEEDED", "RUNNING"):
                status_msg = run_data.get("statusMessage", "")
                log.warning("Apify run failed: %s — %s", run_status, status_msg)
                return {}

            dataset_id = run_data.get("defaultDatasetId")
            if not dataset_id:
                log.warning("No dataset ID in Apify crawl response")
                return {}

            items = await _get_dataset_items(
                client, dataset_id, settings.apify_api_token, limit=len(urls)
            )

            # Build normalized URL -> item mapping from crawl results
            norm_to_item: dict[str, dict] = {}
            for item in items:
                item_url = item.get("url", "")
                if item_url:
                    norm_to_item[_normalize_url(item_url)] = item

            # Match original input URLs to crawl results
            result: dict[str, dict] = {}
            for original_url in urls:
                norm = _normalize_url(original_url)
                if norm in norm_to_item:
                    result[original_url] = norm_to_item[norm]

            log.warning(
                "Batch: crawled %d items, matched %d/%d",
                len(items), len(result), len(urls),
            )

            if len(result) < len(urls):
                crawled_norms = set(norm_to_item.keys())
                input_norms = {_normalize_url(u): u for u in urls}
                unmatched_inputs = set(input_norms.keys()) - crawled_norms
                unmatched_crawled = crawled_norms - set(input_norms.keys())
                if unmatched_inputs:
                    log.warning("Unmatched input: %s", [input_norms[n] for n in list(unmatched_inputs)[:5]])
                if unmatched_crawled:
                    log.warning("Unmatched crawl: %s", list(unmatched_crawled)[:5])

            return result
    except Exception:
        log.warning("Apify batch crawl failed", exc_info=True)
        return {}


async def rag_search(query: str, *, max_results: int = 3, timeout: int = 120) -> list[dict]:
    """Search the web using Apify RAG Web Browser.

    Returns a list of result items (with 'markdown', 'metadata', etc.).
    """
    settings = get_settings()
    if not settings.apify_api_token or not query:
        return []

    actor_id = "apify~rag-web-browser"
    api_url = f"{APIFY_API_BASE}/acts/{actor_id}/runs"

    try:
        async with httpx.AsyncClient(timeout=timeout + 30) as client:
            resp = await client.post(
                api_url,
                params={
                    "token": settings.apify_api_token,
                    "waitForFinish": timeout,
                },
                json={
                    "query": query,
                    "maxResults": max_results,
                    "outputFormats": ["markdown"],
                },
            )
            resp.raise_for_status()
            run_data = resp.json().get("data", resp.json())

            dataset_id = run_data.get("defaultDatasetId")
            if not dataset_id:
                return []

            items = await _get_dataset_items(
                client, dataset_id, settings.apify_api_token, limit=max_results
            )
            return items
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 402:
            log.warning("Apify credit/rate limit hit (402) for: %s", query)
            raise  # Re-raise so caller can stop retrying
        log.warning("Apify RAG search failed for: %s", query, exc_info=True)
        return []
    except Exception:
        log.warning("Apify RAG search failed for: %s", query, exc_info=True)
        return []
