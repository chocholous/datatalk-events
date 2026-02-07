from datetime import datetime
from unittest.mock import patch

import pytest
from sqlmodel import Session, select

from app.models import Event, NotificationLog, ScrapeRun, ScrapeRunStatus, Subscriber, SubscriberStatus

ADMIN_USER = "admin"
ADMIN_PASS = "testpass123"


@pytest.fixture(autouse=True)
def _set_admin_password(monkeypatch):
    """Ensure ADMIN_PASSWORD is set for all admin tests."""
    monkeypatch.setenv("ADMIN_PASSWORD", ADMIN_PASS)
    # Clear the lru_cache so the new env var is picked up
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
    # Create test data
    sub1 = Subscriber(
        email="verified@test.com",
        status=SubscriberStatus.VERIFIED,
        created_at=datetime(2025, 1, 1),
    )
    sub2 = Subscriber(
        email="pending@test.com",
        status=SubscriberStatus.PENDING,
        created_at=datetime(2025, 1, 2),
    )
    event = Event(
        external_id="evt-1",
        title="Test Event",
        url="https://example.com/event1",
        scraped_at=datetime(2025, 6, 1),
    )
    session.add_all([sub1, sub2, event])
    session.commit()

    response = client.get("/admin/", auth=(ADMIN_USER, ADMIN_PASS))
    assert response.status_code == 200
    html = response.text
    # Check that stats are present in the HTML
    assert ">2<" in html  # total subscribers
    assert ">1<" in html  # verified / pending / events each == 1


def test_admin_subscribers_list(client, session: Session):
    sub = Subscriber(
        email="alice@example.com",
        status=SubscriberStatus.VERIFIED,
        created_at=datetime(2025, 3, 15),
    )
    session.add(sub)
    session.commit()

    response = client.get("/admin/subscribers", auth=(ADMIN_USER, ADMIN_PASS))
    assert response.status_code == 200
    assert "alice@example.com" in response.text


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


def test_post_subscriber_creates_subscriber(client, session: Session):
    response = client.post(
        "/admin/subscribers",
        data={"email": "new@example.com", "telegram_chat_id": "", "status": "pending"},
        auth=(ADMIN_USER, ADMIN_PASS),
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "subscriber_added" in response.headers["location"]

    sub = session.exec(
        select(Subscriber).where(Subscriber.email == "new@example.com")
    ).first()
    assert sub is not None
    assert sub.status == SubscriberStatus.PENDING
    assert sub.verified_at is None


def test_post_subscriber_verified_sets_verified_at(client, session: Session):
    response = client.post(
        "/admin/subscribers",
        data={"email": "ver@example.com", "telegram_chat_id": "123", "status": "verified"},
        auth=(ADMIN_USER, ADMIN_PASS),
        follow_redirects=False,
    )
    assert response.status_code == 303

    sub = session.exec(
        select(Subscriber).where(Subscriber.email == "ver@example.com")
    ).first()
    assert sub is not None
    assert sub.status == SubscriberStatus.VERIFIED
    assert sub.verified_at is not None


def test_post_subscriber_duplicate_email_upserts(client, session: Session):
    session.add(Subscriber(email="dup@example.com", status=SubscriberStatus.PENDING))
    session.commit()

    response = client.post(
        "/admin/subscribers",
        data={"email": "dup@example.com", "telegram_chat_id": "999", "status": "verified"},
        auth=(ADMIN_USER, ADMIN_PASS),
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "subscriber_updated" in response.headers["location"]

    sub = session.exec(
        select(Subscriber).where(Subscriber.email == "dup@example.com")
    ).first()
    assert sub is not None
    assert sub.status == SubscriberStatus.VERIFIED
    assert sub.telegram_chat_id == "999"
    assert sub.verified_at is not None


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


def test_get_notifications_returns_200(client, session: Session):
    sub = Subscriber(email="notif@example.com", status=SubscriberStatus.VERIFIED)
    session.add(sub)
    session.commit()
    session.refresh(sub)

    event = Event(
        external_id="evt-notif",
        title="Notif Event",
        url="https://example.com/notif",
    )
    session.add(event)
    session.commit()
    session.refresh(event)

    log = NotificationLog(
        subscriber_id=sub.id,
        event_id=event.id,
        channel="email",
    )
    session.add(log)
    session.commit()

    response = client.get("/admin/notifications", auth=(ADMIN_USER, ADMIN_PASS))
    assert response.status_code == 200
    assert "notif@example.com" in response.text
    assert "Notif Event" in response.text


def test_nav_contains_runs_and_notifications_links(client):
    response = client.get("/admin/", auth=(ADMIN_USER, ADMIN_PASS))
    assert response.status_code == 200
    assert '/admin/runs' in response.text
    assert '/admin/notifications' in response.text


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


def test_subscribers_page_contains_add_form(client):
    response = client.get("/admin/subscribers", auth=(ADMIN_USER, ADMIN_PASS))
    assert response.status_code == 200
    assert 'action="/admin/subscribers"' in response.text
    assert "Add Subscriber" in response.text
