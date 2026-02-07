from datetime import datetime

import pytest
from sqlmodel import Session

from app.models import Event, NotificationLog, Subscriber, SubscriberStatus

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
