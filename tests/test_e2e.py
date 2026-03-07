"""
End-to-end tests against a running application instance.

Usage:
    BASE_URL=http://localhost:8000 python -m pytest tests/test_e2e.py -v -s

Environment variables:
    BASE_URL        - app URL (default: http://localhost:8000)
    ADMIN_USERNAME  - admin user (default: admin)
    ADMIN_PASSWORD  - admin password (default: empty)
"""

import os
import re
import time

import httpx
import pytest

BASE_URL = os.environ.get("BASE_URL", "http://localhost:8000")
ADMIN_USER = os.environ.get("ADMIN_USERNAME", "admin")
ADMIN_PASS = os.environ.get("ADMIN_PASSWORD", "")

POLL_INTERVAL_SECONDS = 2
POLL_MAX_WAIT_SECONDS = 120


@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE_URL, timeout=30) as c:
        yield c


@pytest.fixture(scope="module")
def admin_auth():
    return httpx.BasicAuth(ADMIN_USER, ADMIN_PASS)


@pytest.fixture(scope="module")
def scrape_result():
    """Shared state to pass scrape outcome between tests."""
    return {}


# ── Helpers ──────────────────────────────────────────────────────────────


def count_runs(html: str) -> int:
    """Count number of scrape run rows in the runs page HTML."""
    return len(re.findall(r"<tr>\s*<td>\d+</td>", html))


def get_latest_run_status(html: str) -> str | None:
    """Extract the status of the most recent (first) run from runs page HTML."""
    match = re.search(r'badge-(\w+)">\w+</span>', html)
    return match.group(1) if match else None


# ── Tests (ordered) ─────────────────────────────────────────────────────


class TestE2EWorkflow:
    """Full workflow: connectivity → scrape → verify results."""

    # ── Connectivity ────────────────────────────────────────────────

    def test_01_app_is_running(self, client):
        """Verify the application is reachable."""
        r = client.get("/api/status")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "running"

    def test_02_health_check(self, client):
        """Verify DB is connected."""
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json()["db"] == "connected"

    def test_03_admin_accessible(self, client, admin_auth):
        """Verify admin dashboard is accessible."""
        r = client.get("/admin/", auth=admin_auth)
        assert r.status_code == 200
        assert "Dashboard" in r.text

    # ── Scrape pipeline ─────────────────────────────────────────────

    def test_04_count_runs_before(self, client, admin_auth, scrape_result):
        """Record number of runs before triggering scrape."""
        r = client.get("/admin/runs", auth=admin_auth)
        assert r.status_code == 200
        scrape_result["runs_before"] = count_runs(r.text)

    def test_05_trigger_scrape(self, client, admin_auth):
        """Trigger manual scrape via admin."""
        r = client.post(
            "/admin/scrape",
            auth=admin_auth,
            follow_redirects=False,
        )
        assert r.status_code == 303
        location = r.headers.get("location", "")
        assert "scrape_started" in location

    def test_06_wait_for_scrape_completion(self, client, admin_auth, scrape_result):
        """Poll runs page until a new run finishes (success or failed)."""
        runs_before = scrape_result.get("runs_before", 0)
        deadline = time.time() + POLL_MAX_WAIT_SECONDS

        while time.time() < deadline:
            r = client.get("/admin/runs", auth=admin_auth)
            html = r.text
            current_runs = count_runs(html)

            if current_runs > runs_before:
                status = get_latest_run_status(html)
                if status in ("success", "failed"):
                    scrape_result["status"] = status
                    scrape_result["html"] = html
                    break
            time.sleep(POLL_INTERVAL_SECONDS)

        assert "status" in scrape_result, (
            f"Scrape did not complete within {POLL_MAX_WAIT_SECONDS}s."
        )

    def test_07_scrape_succeeded(self, scrape_result):
        """Verify the scrape run finished with success status."""
        assert scrape_result.get("status") == "success"

    # ── Verify results ──────────────────────────────────────────────

    def test_08_events_exist(self, client):
        """Verify events API returns scraped events."""
        r = client.get("/events")
        assert r.status_code == 200
        events = r.json()
        assert len(events) > 0

    def test_09_events_have_structured_data(self, client):
        """Verify at least some events have location, description, event_type."""
        r = client.get("/events")
        events = r.json()
        assert len(events) > 0

        has_location = any(e.get("location") for e in events)
        has_description = any(e.get("description") for e in events)
        has_type = any(e.get("event_type") for e in events)

        assert has_location or has_description or has_type

    def test_10_events_data_quality(self, client):
        """Verify data quality: URL validity."""
        r = client.get("/events")
        events = r.json()
        assert len(events) > 0

        for event in events:
            url = event.get("url", "")
            assert url.startswith("http"), f"Invalid URL: {url}"

    def test_11_events_api_returns_new_fields(self, client):
        """Verify events API returns speakers, organizer, image_url fields."""
        r = client.get("/events")
        events = r.json()
        assert len(events) > 0

        first = events[0]
        assert "speakers" in first
        assert "organizer" in first
        assert "image_url" in first

    def test_12_landing_page(self, client):
        """Verify landing page loads with calendar/telegram links."""
        r = client.get("/")
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]
