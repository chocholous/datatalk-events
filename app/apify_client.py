"""Apify REST API client for running Actors."""

import logging

import httpx

from app.config import get_settings

log = logging.getLogger(__name__)

APIFY_API_BASE = "https://api.apify.com/v2"


async def run_rag_web_browser(url: str, *, timeout: int = 120) -> dict | None:
    """Fetch a URL using Apify RAG Web Browser Actor.

    Returns the first result item dict (with 'markdown', 'metadata', etc.)
    or None on failure.
    """
    settings = get_settings()
    if not settings.apify_api_token:
        return None

    actor_id = "apify~rag-web-browser"
    api_url = f"{APIFY_API_BASE}/acts/{actor_id}/runs"

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                api_url,
                params={"token": settings.apify_api_token, "waitForFinish": timeout},
                json={
                    "query": url,
                    "maxResults": 1,
                    "outputFormats": ["markdown"],
                },
            )
            resp.raise_for_status()
            run_data = resp.json()

            dataset_id = run_data.get("defaultDatasetId")
            if not dataset_id:
                log.warning("No dataset ID in Apify run response")
                return None

            # Fetch dataset items
            items_resp = await client.get(
                f"{APIFY_API_BASE}/datasets/{dataset_id}/items",
                params={"token": settings.apify_api_token, "limit": 1},
            )
            items_resp.raise_for_status()
            items = items_resp.json()
            if items:
                return items[0]
    except Exception:
        log.warning("Apify RAG web browser failed for: %s", url, exc_info=True)
    return None


async def run_website_content_crawler(
    url: str, *, timeout: int = 120, use_residential_proxy: bool = False
) -> dict | None:
    """Fetch a URL using Apify Website Content Crawler with Playwright.

    Uses headless Firefox for full JS rendering. Optionally uses residential proxy.
    Returns the first result item dict or None on failure.
    """
    settings = get_settings()
    if not settings.apify_api_token:
        return None

    actor_id = "apify~website-content-crawler"
    api_url = f"{APIFY_API_BASE}/acts/{actor_id}/runs"

    input_data = {
        "startUrls": [{"url": url}],
        "crawlerType": "playwright:firefox",
        "maxCrawlDepth": 0,
        "maxCrawlPages": 1,
        "maxResults": 1,
        "saveMarkdown": True,
        "dynamicContentWaitSecs": 15,
    }

    if use_residential_proxy:
        input_data["proxyConfiguration"] = {
            "useApifyProxy": True,
            "apifyProxyGroups": ["RESIDENTIAL"],
        }

    try:
        async with httpx.AsyncClient(timeout=timeout + 30) as client:
            resp = await client.post(
                api_url,
                params={"token": settings.apify_api_token, "waitForFinish": timeout},
                json=input_data,
            )
            resp.raise_for_status()
            run_data = resp.json()

            dataset_id = run_data.get("defaultDatasetId")
            if not dataset_id:
                log.warning("No dataset ID in Apify run response")
                return None

            items_resp = await client.get(
                f"{APIFY_API_BASE}/datasets/{dataset_id}/items",
                params={"token": settings.apify_api_token, "limit": 1},
            )
            items_resp.raise_for_status()
            items = items_resp.json()
            if items:
                return items[0]
    except Exception:
        log.warning("Apify website content crawler failed for: %s", url, exc_info=True)
    return None
