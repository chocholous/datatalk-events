from datetime import datetime

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from app.models import Event, ScrapeRun, ScrapeRunStatus


class TestEventCRUD:
    def test_create_event(self, session) -> None:
        event = Event(
            external_id="evt-001",
            title="Python Meetup",
            url="https://example.com/events/1",
        )
        session.add(event)
        session.commit()
        session.refresh(event)

        assert event.id is not None
        assert event.external_id == "evt-001"
        assert event.title == "Python Meetup"
        assert event.topics == "[]"
        assert isinstance(event.scraped_at, datetime)

    def test_read_event(self, session) -> None:
        event = Event(
            external_id="evt-002",
            title="Data Science Workshop",
            url="https://example.com/events/2",
            location="Prague",
            language="cs",
        )
        session.add(event)
        session.commit()

        result = session.exec(
            select(Event).where(Event.external_id == "evt-002")
        ).first()
        assert result is not None
        assert result.title == "Data Science Workshop"
        assert result.location == "Prague"
        assert result.language == "cs"


class TestEventNewFields:
    def test_event_model_new_fields(self, session) -> None:
        event = Event(
            external_id="evt-new-fields",
            title="New Fields Event",
            url="https://example.com/new-fields",
        )
        session.add(event)
        session.commit()
        session.refresh(event)

        assert event.speakers == "[]"
        assert event.organizer is None
        assert event.image_url is None

    def test_event_with_speakers_and_organizer(self, session) -> None:
        event = Event(
            external_id="evt-speakers",
            title="Speaker Event",
            url="https://example.com/speakers",
            speakers='["Alice", "Bob"]',
            organizer="DataTalk",
            image_url="https://example.com/img.jpg",
        )
        session.add(event)
        session.commit()
        session.refresh(event)

        assert event.speakers == '["Alice", "Bob"]'
        assert event.organizer == "DataTalk"
        assert event.image_url == "https://example.com/img.jpg"


class TestScrapeRunCRUD:
    def test_create_scrape_run_defaults(self, session) -> None:
        run = ScrapeRun()
        session.add(run)
        session.commit()
        session.refresh(run)

        assert run.id is not None
        assert run.status == ScrapeRunStatus.RUNNING
        assert run.events_found == 0
        assert run.events_new == 0
        assert run.finished_at is None
        assert run.error_message is None
        assert isinstance(run.started_at, datetime)


class TestUniqueConstraints:
    def test_duplicate_event_external_id_raises(self, session) -> None:
        session.add(
            Event(
                external_id="dup-evt",
                title="Event A",
                url="https://example.com/a",
            )
        )
        session.commit()

        session.add(
            Event(
                external_id="dup-evt",
                title="Event B",
                url="https://example.com/b",
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
