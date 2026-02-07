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
        {"title": "Ev1", "url": "https://example.com/1", "type": "meetup"},
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
async def test_pipeline_deletes_old_events(pipeline_session):
    """Verify old events are deleted at the start of a pipeline run."""
    # Pre-populate with an old event
    old_event = Event(
        external_id="old-evt",
        title="Old Event",
        url="https://example.com/old",
    )
    pipeline_session.add(old_event)
    pipeline_session.commit()

    events_before = pipeline_session.exec(select(Event)).all()
    assert len(events_before) == 1

    raw_events = [{"title": "New", "url": "https://example.com/new"}]
    enriched_events = [{"title": "New", "url": "https://example.com/new", "type": "meetup"}]

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
    # Old event gone, only new event remains
    assert len(events_after) == 1
    assert events_after[0].title == "New"


@pytest.mark.anyio
async def test_pipeline_saves_new_fields(pipeline_session):
    """Verify speakers, organizer, image_url are saved to Event."""
    raw_events = [{"title": "Ev", "url": "https://example.com/ev"}]
    enriched_events = [
        {
            "title": "Ev",
            "url": "https://example.com/ev",
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
