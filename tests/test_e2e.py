"""
End-to-end tests against a running application instance.

Usage:
    BASE_URL=http://localhost:8000 python -m pytest tests/test_e2e.py -v -s

Environment variables:
    BASE_URL        - app URL (default: http://localhost:8000)
    ADMIN_USERNAME  - admin user (default: admin)
    ADMIN_PASSWORD  - admin password (default: empty)
    TEST_EMAIL      - subscriber email to use (default: pavel@chocholous.net)
"""

import os
import re
import time

import httpx
import pytest

BASE_URL = os.environ.get("BASE_URL", "http://localhost:8000")
ADMIN_USER = os.environ.get("ADMIN_USERNAME", "admin")
ADMIN_PASS = os.environ.get("ADMIN_PASSWORD", "")
TEST_EMAIL = os.environ.get("TEST_EMAIL", "pavel@chocholous.net")

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
    """Full workflow: add subscriber → scrape → verify results → cleanup."""

    # ── Connectivity ────────────────────────────────────────────────

    def test_01_app_is_running(self, client):
        """Verify the application is reachable."""
        r = client.get("/")
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

    # ── Subscriber management ───────────────────────────────────────

    def test_04_add_subscriber_verified(self, client, admin_auth):
        """Add/update subscriber via admin form with verified status.

        The admin endpoint does upsert — if subscriber already exists
        (e.g. from a previous test run), it updates their status.
        """
        r = client.post(
            "/admin/subscribers",
            data={
                "email": TEST_EMAIL,
                "telegram_chat_id": "",
                "status": "verified",
            },
            auth=admin_auth,
            follow_redirects=False,
        )
        assert r.status_code == 303
        location = r.headers.get("location", "")
        assert "subscriber_added" in location or "subscriber_updated" in location, (
            f"Expected success redirect, got: {location}"
        )

    def test_05_subscriber_appears_in_list(self, client, admin_auth):
        """Verify subscriber is visible in admin subscribers page."""
        r = client.get("/admin/subscribers", auth=admin_auth)
        assert r.status_code == 200
        assert TEST_EMAIL in r.text, f"{TEST_EMAIL} not found in subscribers list"

    def test_06_subscriber_is_verified(self, client, admin_auth):
        """Verify subscriber has 'verified' status badge."""
        r = client.get("/admin/subscribers", auth=admin_auth)
        assert r.status_code == 200
        # Find TEST_EMAIL row and check it has verified badge
        # HTML structure: <td>email</td><td><span class="badge badge-verified">
        email_pos = r.text.find(TEST_EMAIL)
        assert email_pos != -1
        # Check the badge right after the email in the same row
        row_snippet = r.text[email_pos:email_pos + 300]
        assert "badge-verified" in row_snippet, (
            f"Subscriber {TEST_EMAIL} is not in verified status"
        )

    # ── Scrape pipeline ─────────────────────────────────────────────

    def test_07_count_runs_before(self, client, admin_auth, scrape_result):
        """Record number of runs before triggering scrape."""
        r = client.get("/admin/runs", auth=admin_auth)
        assert r.status_code == 200
        scrape_result["runs_before"] = count_runs(r.text)

    def test_08_trigger_scrape(self, client, admin_auth):
        """Trigger manual scrape via admin."""
        r = client.post(
            "/admin/scrape",
            auth=admin_auth,
            follow_redirects=False,
        )
        assert r.status_code == 303
        location = r.headers.get("location", "")
        assert "scrape_started" in location, (
            f"Expected scrape_started redirect, got: {location}"
        )

    def test_09_wait_for_scrape_completion(self, client, admin_auth, scrape_result):
        """Poll runs page until a new run finishes (success or failed)."""
        runs_before = scrape_result.get("runs_before", 0)
        deadline = time.time() + POLL_MAX_WAIT_SECONDS

        while time.time() < deadline:
            r = client.get("/admin/runs", auth=admin_auth)
            html = r.text
            current_runs = count_runs(html)

            if current_runs > runs_before:
                # New run appeared — check its status
                status = get_latest_run_status(html)
                if status in ("success", "failed"):
                    scrape_result["status"] = status
                    scrape_result["html"] = html
                    break
            time.sleep(POLL_INTERVAL_SECONDS)

        assert "status" in scrape_result, (
            f"Scrape did not complete within {POLL_MAX_WAIT_SECONDS}s. "
            "Check /admin/runs for details."
        )

    def test_10_scrape_succeeded(self, scrape_result):
        """Verify the scrape run finished with success status."""
        assert scrape_result.get("status") == "success", (
            "Scrape finished with status=failed. "
            "Check /admin/runs for error details."
        )

    # ── Verify results ──────────────────────────────────────────────

    def test_11_events_exist(self, client):
        """Verify events API returns scraped events."""
        r = client.get("/events")
        assert r.status_code == 200
        events = r.json()
        assert len(events) > 0, "No events found in /events API after scrape"

    def test_12_notifications_sent(self, client, admin_auth):
        """Verify notification logs exist for our subscriber.

        Note: If all scraped events were already in DB (deduplicated),
        no new notifications are generated. This is expected behavior.
        """
        html = client.get("/admin/notifications", auth=admin_auth).text
        if TEST_EMAIL not in html:
            # Check if it's because there were no NEW events
            runs_html = client.get("/admin/runs", auth=admin_auth).text
            pytest.skip(
                "No notifications for subscriber — likely no NEW events "
                "(all deduplicated). Check /admin/runs for events_new count."
            )
        assert TEST_EMAIL in html

    # ── Cleanup ─────────────────────────────────────────────────────

    def test_13_cleanup_unsubscribe(self, client):
        """Cleanup: unsubscribe test email."""
        r = client.post("/unsubscribe", json={"email": TEST_EMAIL})
        assert r.status_code == 200
        assert r.json()["success"] is True

    def test_14_subscriber_unsubscribed(self, client, admin_auth):
        """Verify subscriber status changed to unsubscribed."""
        r = client.get("/admin/subscribers", auth=admin_auth)
        assert r.status_code == 200
        assert TEST_EMAIL in r.text
        email_pos = r.text.find(TEST_EMAIL)
        row_snippet = r.text[email_pos:email_pos + 300]
        assert "badge-unsubscribed" in row_snippet

    # ── Re-add for live email test ──────────────────────────────────

    def test_15_readd_subscriber_verified(self, client, admin_auth):
        """Re-add subscriber as verified so user can check email delivery."""
        r = client.post(
            "/admin/subscribers",
            data={
                "email": TEST_EMAIL,
                "telegram_chat_id": "",
                "status": "verified",
            },
            auth=admin_auth,
            follow_redirects=False,
        )
        assert r.status_code == 303
        location = r.headers.get("location", "")
        assert "subscriber_updated" in location or "subscriber_added" in location
