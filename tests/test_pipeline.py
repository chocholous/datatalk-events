from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.models import Event, NotificationLog, Subscriber, SubscriberStatus
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


@pytest.mark.anyio
async def test_pipeline_full_flow(pipeline_session):
    """Mock scraper + extractor + notifiers: events saved, notifications logged."""
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
        }
    ]

    mock_scraper = AsyncMock()
    mock_scraper.scrape.return_value = raw_events

    mock_extractor = AsyncMock()
    mock_extractor.extract.return_value = enriched_events

    mock_email_sender = AsyncMock()
    mock_email_sender.send.return_value = True

    mock_telegram = AsyncMock()
    mock_telegram.send_message.return_value = True

    with (
        patch(
            "app.notifications.pipeline.Scraper", return_value=mock_scraper
        ),
        patch(
            "app.notifications.pipeline.EventExtractor",
            return_value=mock_extractor,
        ),
        patch(
            "app.notifications.pipeline.get_email_sender",
            return_value=mock_email_sender,
        ),
        patch(
            "app.notifications.pipeline.TelegramNotifier",
            return_value=mock_telegram,
        ),
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


@pytest.mark.anyio
async def test_pipeline_no_events(pipeline_session):
    """Scraper returns empty list: no notifications sent."""
    mock_scraper = AsyncMock()
    mock_scraper.scrape.return_value = []

    with patch(
        "app.notifications.pipeline.Scraper", return_value=mock_scraper
    ):
        await run_scrape_and_notify(pipeline_session)

    # No events saved
    events = pipeline_session.exec(select(Event)).all()
    assert len(events) == 0

    # No notifications logged
    logs = pipeline_session.exec(select(NotificationLog)).all()
    assert len(logs) == 0
