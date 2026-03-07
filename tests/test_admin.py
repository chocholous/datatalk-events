from datetime import datetime
from unittest.mock import patch

from sqlmodel import Session

from app.models import Event, ScrapeRun, ScrapeRunStatus

ADMIN_USER = "admin"
ADMIN_PASS = "testpass123"


def _set_admin(monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD", ADMIN_PASS)
    from app.config import get_settings
    get_settings.cache_clear()


import pytest


@pytest.fixture(autouse=True)
def _set_admin_password(monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD", ADMIN_PASS)
    from app.config import get_settings
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_admin_without_credentials_returns_401(client):
    response = client.get("/admin/")
    assert response.status_code == 401


def test_admin_with_valid_credentials_returns_200(client):
    response = client.get("/admin/", auth=(ADMIN_USER, ADMIN_PASS))
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


def test_admin_dashboard_shows_stats(client, session: Session):
    event = Event(
        external_id="evt-1",
        title="Test Event",
        url="https://example.com/event1",
        scraped_at=datetime(2025, 6, 1),
    )
    session.add(event)
    session.commit()

    response = client.get("/admin/", auth=(ADMIN_USER, ADMIN_PASS))
    assert response.status_code == 200
    html = response.text
    assert ">1<" in html  # total events


def test_admin_events_list(client, session: Session):
    event = Event(
        external_id="evt-42",
        title="Prague Data Meetup",
        url="https://example.com/meetup",
        location="Prague",
        event_type="meetup",
        scraped_at=datetime(2025, 7, 1),
    )
    session.add(event)
    session.commit()

    response = client.get("/admin/events", auth=(ADMIN_USER, ADMIN_PASS))
    assert response.status_code == 200
    assert "Prague Data Meetup" in response.text


def test_post_scrape_returns_redirect(client):
    with patch("app.routers.admin._run_pipeline"):
        response = client.post(
            "/admin/scrape",
            auth=(ADMIN_USER, ADMIN_PASS),
            follow_redirects=False,
        )
    assert response.status_code == 303
    assert "/admin/" in response.headers["location"]
    assert "scrape_started" in response.headers["location"]


def test_get_runs_returns_200(client, session: Session):
    run = ScrapeRun(
        status=ScrapeRunStatus.SUCCESS,
        events_found=5,
        events_new=2,
        finished_at=datetime(2025, 8, 1),
    )
    session.add(run)
    session.commit()

    response = client.get("/admin/runs", auth=(ADMIN_USER, ADMIN_PASS))
    assert response.status_code == 200
    assert "success" in response.text


def test_dashboard_contains_scrape_form(client):
    response = client.get("/admin/", auth=(ADMIN_USER, ADMIN_PASS))
    assert response.status_code == 200
    assert 'action="/admin/scrape"' in response.text
    assert "Run Scraper Now" in response.text


def test_admin_events_shows_speakers_and_organizer(client, session: Session):
    event = Event(
        external_id="evt-speakers",
        title="Speaker Event",
        url="https://example.com/speakers",
        speakers='["Alice", "Bob"]',
        organizer="DataTalk CZ",
        description="A great event about data engineering and AI.",
        scraped_at=datetime(2025, 9, 1),
    )
    session.add(event)
    session.commit()

    response = client.get("/admin/events", auth=(ADMIN_USER, ADMIN_PASS))
    assert response.status_code == 200
    html = response.text
    assert "Speaker Event" in html
    assert "Alice" in html
    assert "Bob" in html
    assert "DataTalk CZ" in html
    assert "A great event about data" in html


def test_nav_contains_runs_link(client):
    response = client.get("/admin/", auth=(ADMIN_USER, ADMIN_PASS))
    assert response.status_code == 200
    assert '/admin/runs' in response.text
