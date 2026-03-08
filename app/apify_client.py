"""Apify REST API client for running Actors."""

import logging

import httpx

from app.config import get_settings

log = logging.getLogger(__name__)

APIFY_API_BASE = "https://api.apify.com/v2"


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


async def crawl_urls(
    urls: list[str], *, timeout: int = 300, use_residential_proxy: bool = True
) -> dict[str, dict]:
    """Batch-crawl URLs using Apify Website Content Crawler with Playwright.

    Returns a dict mapping URL -> result item (with 'markdown', 'url', etc.).
    Missing URLs are not included in the result.
    """
    settings = get_settings()
    if not settings.apify_api_token or not urls:
        return {}

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

            dataset_id = run_data.get("defaultDatasetId")
            if not dataset_id:
                log.warning("No dataset ID in Apify crawl response")
                return {}

            items = await _get_dataset_items(
                client, dataset_id, settings.apify_api_token, limit=len(urls)
            )

            # Map results by URL
            result = {}
            for item in items:
                item_url = item.get("url", "")
                if item_url:
                    result[item_url] = item
            log.info("Apify crawled %d/%d URLs", len(result), len(urls))
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
    except Exception:
        log.warning("Apify RAG search failed for: %s", query, exc_info=True)
        return []
