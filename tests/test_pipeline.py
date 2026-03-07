from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.models import Event, ScrapeRun, ScrapeRunStatus, Subscriber, SubscriberStatus
from app.notifications.pipeline import run_scrape_and_notify, send_daily_reminders


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


# Future date for events
FUTURE_DATE = (datetime.utcnow() + timedelta(days=30)).isoformat()


def _make_mocks(raw_events, enriched_events):
    """Create standard mocks for pipeline components."""
    mock_scraper = AsyncMock()
    mock_scraper.scrape.return_value = raw_events

    mock_detail_fetcher = AsyncMock()
    mock_detail_fetcher.fetch_details.return_value = raw_events

    mock_extractor = AsyncMock()
    mock_extractor.extract.return_value = enriched_events

    return mock_scraper, mock_detail_fetcher, mock_extractor


def _pipeline_patches(mock_scraper, mock_detail_fetcher, mock_extractor):
    return (
        patch("app.notifications.pipeline.Scraper", return_value=mock_scraper),
        patch("app.notifications.pipeline.DetailFetcher", return_value=mock_detail_fetcher),
        patch("app.notifications.pipeline.EventExtractor", return_value=mock_extractor),
        patch("app.notifications.pipeline.sync_events_to_google_calendar", return_value=1),
    )


@pytest.mark.anyio
async def test_pipeline_full_flow(pipeline_session):
    """Events are saved and synced to Google Calendar."""
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

    mock_scraper, mock_detail_fetcher, mock_extractor = _make_mocks(raw_events, enriched_events)
    mock_gcal = patch("app.notifications.pipeline.sync_events_to_google_calendar", return_value=1)

    with (
        patch("app.notifications.pipeline.Scraper", return_value=mock_scraper),
        patch("app.notifications.pipeline.DetailFetcher", return_value=mock_detail_fetcher),
        patch("app.notifications.pipeline.EventExtractor", return_value=mock_extractor),
        mock_gcal as gcal_mock,
    ):
        await run_scrape_and_notify(pipeline_session)

    # Verify events were saved
    events = pipeline_session.exec(select(Event)).all()
    assert len(events) == 1
    assert events[0].title == "Test Event"
    assert events[0].location == "Prague"

    # Verify Google Calendar sync was called
    gcal_mock.assert_called_once()

    # Verify ScrapeRun was created with correct status
    runs = pipeline_session.exec(select(ScrapeRun)).all()
    assert len(runs) == 1
    assert runs[0].status == ScrapeRunStatus.SUCCESS
    assert runs[0].events_found == 1
    assert runs[0].events_new == 1
    assert runs[0].finished_at is not None


@pytest.mark.anyio
async def test_pipeline_no_events(pipeline_session):
    """Scraper returns empty list: no sync performed."""
    mock_scraper = AsyncMock()
    mock_scraper.scrape.return_value = []

    with (
        patch("app.notifications.pipeline.Scraper", return_value=mock_scraper),
        patch("app.notifications.pipeline.DetailFetcher"),
    ):
        await run_scrape_and_notify(pipeline_session)

    events = pipeline_session.exec(select(Event)).all()
    assert len(events) == 0

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
    raw_events = [{"title": "Ev1", "url": "https://example.com/1"}]
    enriched_events = [
        {"title": "Ev1", "url": "https://example.com/1", "date": FUTURE_DATE, "type": "meetup"}
    ]

    mock_scraper, mock_detail_fetcher, mock_extractor = _make_mocks(raw_events, enriched_events)
    p = _pipeline_patches(mock_scraper, mock_detail_fetcher, mock_extractor)

    with p[0], p[1], p[2], p[3]:
        await run_scrape_and_notify(pipeline_session)

    mock_detail_fetcher.fetch_details.assert_called_once_with(raw_events)
    mock_extractor.extract.assert_called_once()


@pytest.mark.anyio
async def test_pipeline_upserts_events(pipeline_session):
    """Verify existing events are updated (not duplicated) on re-scrape."""
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

    raw_events = [{"title": "New Title", "url": url}]
    enriched_events = [{"title": "New Title", "url": url, "location": "New Location", "type": "meetup"}]

    mock_scraper, mock_detail_fetcher, mock_extractor = _make_mocks(raw_events, enriched_events)
    p = _pipeline_patches(mock_scraper, mock_detail_fetcher, mock_extractor)

    with p[0], p[1], p[2], p[3]:
        await run_scrape_and_notify(pipeline_session)

    events_after = pipeline_session.exec(select(Event)).all()
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

    mock_scraper, mock_detail_fetcher, mock_extractor = _make_mocks(raw_events, enriched_events)
    p = _pipeline_patches(mock_scraper, mock_detail_fetcher, mock_extractor)

    with p[0], p[1], p[2], p[3]:
        await run_scrape_and_notify(pipeline_session)

    events = pipeline_session.exec(select(Event)).all()
    assert len(events) == 1
    ev = events[0]
    assert ev.speakers == '["Alice", "Bob"]'
    assert ev.organizer == "DataTalk CZ"
    assert ev.image_url == "https://example.com/banner.jpg"
    assert ev.description == "Popis eventu pro testovani"


@pytest.mark.anyio
async def test_daily_reminders_sends_for_today(pipeline_session):
    """Daily reminder sends Telegram message for today's events."""
    now = datetime.utcnow()
    event = Event(
        external_id="today-1",
        title="Today Event",
        url="https://example.com/today",
        date=now.replace(hour=14, minute=0),
    )
    pipeline_session.add(event)
    pipeline_session.commit()

    mock_telegram = AsyncMock()
    mock_telegram.send_to_channel.return_value = True

    with patch("app.notifications.pipeline.TelegramNotifier", return_value=mock_telegram):
        await send_daily_reminders(pipeline_session)

    mock_telegram.send_to_channel.assert_called_once()


@pytest.mark.anyio
async def test_daily_reminders_skips_no_events(pipeline_session):
    """Daily reminder does nothing when no events today."""
    mock_telegram = AsyncMock()

    with patch("app.notifications.pipeline.TelegramNotifier", return_value=mock_telegram):
        await send_daily_reminders(pipeline_session)

    mock_telegram.send_to_channel.assert_not_called()
