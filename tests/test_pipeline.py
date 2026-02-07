from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.models import Event, NotificationLog, ScrapeRun, ScrapeRunStatus, Subscriber, SubscriberStatus
from app.notifications.pipeline import run_scrape_and_notify


@pytest.fixture(name="pipeline_session")
def pipeline_session_fixture():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


# Future date for events that should trigger notifications
FUTURE_DATE = (datetime.utcnow() + timedelta(days=30)).isoformat()


def _make_mocks(raw_events, enriched_events):
    """Create standard mocks for pipeline components."""
    mock_scraper = AsyncMock()
    mock_scraper.scrape.return_value = raw_events

    mock_detail_fetcher = AsyncMock()
    # Detail fetcher returns enriched_raw (same as raw + detail data)
    mock_detail_fetcher.fetch_details.return_value = raw_events

    mock_extractor = AsyncMock()
    mock_extractor.extract.return_value = enriched_events

    mock_email_sender = AsyncMock()
    mock_email_sender.send.return_value = True

    mock_telegram = AsyncMock()
    mock_telegram.send_message.return_value = True

    return mock_scraper, mock_detail_fetcher, mock_extractor, mock_email_sender, mock_telegram


@pytest.mark.anyio
async def test_pipeline_full_flow(pipeline_session):
    """Mock scraper + detail_fetcher + extractor + notifiers: events saved, notifications logged."""
    # Create a verified subscriber
    sub = Subscriber(
        email="test@example.com",
        status=SubscriberStatus.VERIFIED,
        telegram_chat_id="12345",
    )
    pipeline_session.add(sub)
    pipeline_session.commit()

    raw_events = [
        {
            "title": "Test Event",
            "url": "https://example.com/event-1",
            "description": "A test event",
        }
    ]
    enriched_events = [
        {
            "title": "Test Event",
            "url": "https://example.com/event-1",
            "date": FUTURE_DATE,
            "description": "A test event",
            "location": "Prague",
            "topics": ["AI"],
            "type": "meetup",
            "language": "cs",
            "speakers": ["John Doe"],
            "organizer": "DataTalk",
            "image_url": "https://example.com/img.jpg",
        }
    ]

    mock_scraper, mock_detail_fetcher, mock_extractor, mock_email_sender, mock_telegram = (
        _make_mocks(raw_events, enriched_events)
    )

    with (
        patch("app.notifications.pipeline.Scraper", return_value=mock_scraper),
        patch("app.notifications.pipeline.DetailFetcher", return_value=mock_detail_fetcher),
        patch("app.notifications.pipeline.EventExtractor", return_value=mock_extractor),
        patch("app.notifications.pipeline.get_email_sender", return_value=mock_email_sender),
        patch("app.notifications.pipeline.TelegramNotifier", return_value=mock_telegram),
    ):
        await run_scrape_and_notify(pipeline_session)

    # Verify events were saved
    events = pipeline_session.exec(select(Event)).all()
    assert len(events) == 1
    assert events[0].title == "Test Event"
    assert events[0].location == "Prague"

    # Verify notifications were logged
    logs = pipeline_session.exec(select(NotificationLog)).all()
    assert len(logs) == 2  # email + telegram
    channels = {log.channel for log in logs}
    assert channels == {"email", "telegram"}

    # Verify email and telegram were called
    mock_email_sender.send.assert_called_once()
    mock_telegram.send_message.assert_called_once()

    # Verify ScrapeRun was created with correct status
    runs = pipeline_session.exec(select(ScrapeRun)).all()
    assert len(runs) == 1
    assert runs[0].status == ScrapeRunStatus.SUCCESS
    assert runs[0].events_found == 1
    assert runs[0].events_new == 1
    assert runs[0].finished_at is not None


@pytest.mark.anyio
async def test_pipeline_no_events(pipeline_session):
    """Scraper returns empty list: no notifications sent."""
    mock_scraper = AsyncMock()
    mock_scraper.scrape.return_value = []

    with (
        patch("app.notifications.pipeline.Scraper", return_value=mock_scraper),
        patch("app.notifications.pipeline.DetailFetcher"),
    ):
        await run_scrape_and_notify(pipeline_session)

    # No events saved
    events = pipeline_session.exec(select(Event)).all()
    assert len(events) == 0

    # No notifications logged
    logs = pipeline_session.exec(select(NotificationLog)).all()
    assert len(logs) == 0

    # ScrapeRun recorded with SUCCESS and 0 events
    runs = pipeline_session.exec(select(ScrapeRun)).all()
    assert len(runs) == 1
    assert runs[0].status == ScrapeRunStatus.SUCCESS
    assert runs[0].events_found == 0
    assert runs[0].finished_at is not None


@pytest.mark.anyio
async def test_pipeline_creates_scrape_run_on_failure(pipeline_session):
    """ScrapeRun is marked FAILED when an exception occurs."""
    mock_scraper = AsyncMock()
    mock_scraper.scrape.side_effect = RuntimeError("scrape failed")

    with (
        patch("app.notifications.pipeline.Scraper", return_value=mock_scraper),
        patch("app.notifications.pipeline.DetailFetcher"),
        pytest.raises(RuntimeError, match="scrape failed"),
    ):
        await run_scrape_and_notify(pipeline_session)

    runs = pipeline_session.exec(select(ScrapeRun)).all()
    assert len(runs) == 1
    assert runs[0].status == ScrapeRunStatus.FAILED
    assert runs[0].error_message == "scrape failed"
    assert runs[0].finished_at is not None


@pytest.mark.anyio
async def test_pipeline_calls_detail_fetcher(pipeline_session):
    """Verify DetailFetcher.fetch_details is called with raw events."""
    raw_events = [
        {"title": "Ev1", "url": "https://example.com/1"},
    ]
    enriched_events = [
        {"title": "Ev1", "url": "https://example.com/1", "date": FUTURE_DATE, "type": "meetup"},
    ]

    mock_scraper, mock_detail_fetcher, mock_extractor, mock_email_sender, mock_telegram = (
        _make_mocks(raw_events, enriched_events)
    )

    with (
        patch("app.notifications.pipeline.Scraper", return_value=mock_scraper),
        patch("app.notifications.pipeline.DetailFetcher", return_value=mock_detail_fetcher),
        patch("app.notifications.pipeline.EventExtractor", return_value=mock_extractor),
        patch("app.notifications.pipeline.get_email_sender", return_value=mock_email_sender),
        patch("app.notifications.pipeline.TelegramNotifier", return_value=mock_telegram),
    ):
        await run_scrape_and_notify(pipeline_session)

    mock_detail_fetcher.fetch_details.assert_called_once_with(raw_events)
    # Extractor gets the result of detail_fetcher
    mock_extractor.extract.assert_called_once()


@pytest.mark.anyio
async def test_pipeline_upserts_events(pipeline_session):
    """Verify existing events are updated (not duplicated) on re-scrape."""
    # Pre-populate with an existing event (same URL = same external_id)
    import hashlib
    url = "https://example.com/existing"
    ext_id = hashlib.md5(url.encode()).hexdigest()[:16]
    old_event = Event(
        external_id=ext_id,
        title="Old Title",
        url=url,
        location="Old Location",
    )
    pipeline_session.add(old_event)
    pipeline_session.commit()

    events_before = pipeline_session.exec(select(Event)).all()
    assert len(events_before) == 1

    raw_events = [{"title": "New Title", "url": url}]
    enriched_events = [{"title": "New Title", "url": url, "location": "New Location", "type": "meetup"}]

    mock_scraper, mock_detail_fetcher, mock_extractor, mock_email_sender, mock_telegram = (
        _make_mocks(raw_events, enriched_events)
    )

    with (
        patch("app.notifications.pipeline.Scraper", return_value=mock_scraper),
        patch("app.notifications.pipeline.DetailFetcher", return_value=mock_detail_fetcher),
        patch("app.notifications.pipeline.EventExtractor", return_value=mock_extractor),
        patch("app.notifications.pipeline.get_email_sender", return_value=mock_email_sender),
        patch("app.notifications.pipeline.TelegramNotifier", return_value=mock_telegram),
    ):
        await run_scrape_and_notify(pipeline_session)

    events_after = pipeline_session.exec(select(Event)).all()
    # Same event updated, not duplicated
    assert len(events_after) == 1
    assert events_after[0].title == "New Title"
    assert events_after[0].location == "New Location"


@pytest.mark.anyio
async def test_pipeline_saves_new_fields(pipeline_session):
    """Verify speakers, organizer, image_url are saved to Event."""
    raw_events = [{"title": "Ev", "url": "https://example.com/ev"}]
    enriched_events = [
        {
            "title": "Ev",
            "url": "https://example.com/ev",
            "date": FUTURE_DATE,
            "type": "conference",
            "speakers": ["Alice", "Bob"],
            "organizer": "DataTalk CZ",
            "image_url": "https://example.com/banner.jpg",
            "description": "Popis eventu pro testovani",
        }
    ]

    mock_scraper, mock_detail_fetcher, mock_extractor, mock_email_sender, mock_telegram = (
        _make_mocks(raw_events, enriched_events)
    )

    with (
        patch("app.notifications.pipeline.Scraper", return_value=mock_scraper),
        patch("app.notifications.pipeline.DetailFetcher", return_value=mock_detail_fetcher),
        patch("app.notifications.pipeline.EventExtractor", return_value=mock_extractor),
        patch("app.notifications.pipeline.get_email_sender", return_value=mock_email_sender),
        patch("app.notifications.pipeline.TelegramNotifier", return_value=mock_telegram),
    ):
        await run_scrape_and_notify(pipeline_session)

    events = pipeline_session.exec(select(Event)).all()
    assert len(events) == 1
    ev = events[0]
    assert ev.speakers == '["Alice", "Bob"]'
    assert ev.organizer == "DataTalk CZ"
    assert ev.image_url == "https://example.com/banner.jpg"
    assert ev.description == "Popis eventu pro testovani"


@pytest.mark.anyio
async def test_pipeline_skips_already_notified(pipeline_session):
    """Subscriber should not be notified again about same event."""
    sub = Subscriber(
        email="test@example.com",
        status=SubscriberStatus.VERIFIED,
    )
    pipeline_session.add(sub)
    pipeline_session.commit()
    pipeline_session.refresh(sub)

    raw_events = [{"title": "Ev", "url": "https://example.com/ev"}]
    enriched_events = [
        {"title": "Ev", "url": "https://example.com/ev", "date": FUTURE_DATE, "type": "meetup"}
    ]

    mock_scraper, mock_detail_fetcher, mock_extractor, mock_email_sender, mock_telegram = (
        _make_mocks(raw_events, enriched_events)
    )

    patches = (
        patch("app.notifications.pipeline.Scraper", return_value=mock_scraper),
        patch("app.notifications.pipeline.DetailFetcher", return_value=mock_detail_fetcher),
        patch("app.notifications.pipeline.EventExtractor", return_value=mock_extractor),
        patch("app.notifications.pipeline.get_email_sender", return_value=mock_email_sender),
        patch("app.notifications.pipeline.TelegramNotifier", return_value=mock_telegram),
    )

    # First run — should notify
    with patches[0], patches[1], patches[2], patches[3], patches[4]:
        await run_scrape_and_notify(pipeline_session)

    assert mock_email_sender.send.call_count == 1
    logs = pipeline_session.exec(select(NotificationLog)).all()
    assert len(logs) == 1  # email only (no telegram_chat_id)

    # Second run — same event, should NOT notify again
    mock_email_sender.reset_mock()
    mock_scraper2, mock_detail_fetcher2, mock_extractor2, mock_email_sender2, mock_telegram2 = (
        _make_mocks(raw_events, enriched_events)
    )
    with (
        patch("app.notifications.pipeline.Scraper", return_value=mock_scraper2),
        patch("app.notifications.pipeline.DetailFetcher", return_value=mock_detail_fetcher2),
        patch("app.notifications.pipeline.EventExtractor", return_value=mock_extractor2),
        patch("app.notifications.pipeline.get_email_sender", return_value=mock_email_sender2),
        patch("app.notifications.pipeline.TelegramNotifier", return_value=mock_telegram2),
    ):
        await run_scrape_and_notify(pipeline_session)

    # No new notifications sent
    mock_email_sender2.send.assert_not_called()
    logs_after = pipeline_session.exec(select(NotificationLog)).all()
    assert len(logs_after) == 1  # Still just the original one


@pytest.mark.anyio
async def test_pipeline_skips_past_events(pipeline_session):
    """Past events should not trigger notifications."""
    sub = Subscriber(
        email="test@example.com",
        status=SubscriberStatus.VERIFIED,
    )
    pipeline_session.add(sub)
    pipeline_session.commit()

    past_date = (datetime.utcnow() - timedelta(days=7)).isoformat()
    raw_events = [{"title": "Past Ev", "url": "https://example.com/past"}]
    enriched_events = [
        {"title": "Past Ev", "url": "https://example.com/past", "date": past_date, "type": "meetup"}
    ]

    mock_scraper, mock_detail_fetcher, mock_extractor, mock_email_sender, mock_telegram = (
        _make_mocks(raw_events, enriched_events)
    )

    with (
        patch("app.notifications.pipeline.Scraper", return_value=mock_scraper),
        patch("app.notifications.pipeline.DetailFetcher", return_value=mock_detail_fetcher),
        patch("app.notifications.pipeline.EventExtractor", return_value=mock_extractor),
        patch("app.notifications.pipeline.get_email_sender", return_value=mock_email_sender),
        patch("app.notifications.pipeline.TelegramNotifier", return_value=mock_telegram),
    ):
        await run_scrape_and_notify(pipeline_session)

    # Event saved but no notifications sent (past event)
    events = pipeline_session.exec(select(Event)).all()
    assert len(events) == 1
    mock_email_sender.send.assert_not_called()
    logs = pipeline_session.exec(select(NotificationLog)).all()
    assert len(logs) == 0
