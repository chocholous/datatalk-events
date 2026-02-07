from datetime import datetime

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from app.models import Event, NotificationLog, Subscriber, SubscriberStatus


class TestSubscriberCRUD:
    def test_create_subscriber(self, session) -> None:
        subscriber = Subscriber(email="alice@example.com")
        session.add(subscriber)
        session.commit()
        session.refresh(subscriber)

        assert subscriber.id is not None
        assert subscriber.email == "alice@example.com"
        assert subscriber.status == SubscriberStatus.PENDING
        assert subscriber.preferences == "{}"
        assert isinstance(subscriber.created_at, datetime)

    def test_read_subscriber(self, session) -> None:
        subscriber = Subscriber(email="bob@example.com")
        session.add(subscriber)
        session.commit()

        result = session.exec(
            select(Subscriber).where(Subscriber.email == "bob@example.com")
        ).first()
        assert result is not None
        assert result.email == "bob@example.com"

    def test_update_subscriber(self, session) -> None:
        subscriber = Subscriber(email="carol@example.com")
        session.add(subscriber)
        session.commit()

        subscriber.status = SubscriberStatus.VERIFIED
        subscriber.verified_at = datetime.utcnow()
        session.add(subscriber)
        session.commit()
        session.refresh(subscriber)

        assert subscriber.status == SubscriberStatus.VERIFIED
        assert subscriber.verified_at is not None


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


class TestNotificationLogCRUD:
    def test_create_notification_log(self, session) -> None:
        subscriber = Subscriber(email="dave@example.com")
        session.add(subscriber)
        session.commit()
        session.refresh(subscriber)

        event = Event(
            external_id="evt-010",
            title="AI Conference",
            url="https://example.com/events/10",
        )
        session.add(event)
        session.commit()
        session.refresh(event)

        log = NotificationLog(
            subscriber_id=subscriber.id,
            event_id=event.id,
            channel="email",
        )
        session.add(log)
        session.commit()
        session.refresh(log)

        assert log.id is not None
        assert log.subscriber_id == subscriber.id
        assert log.event_id == event.id
        assert log.channel == "email"
        assert log.status == "sent"
        assert isinstance(log.sent_at, datetime)


class TestUniqueConstraints:
    def test_duplicate_subscriber_email_raises(self, session) -> None:
        session.add(Subscriber(email="dup@example.com"))
        session.commit()

        session.add(Subscriber(email="dup@example.com"))
        with pytest.raises(IntegrityError):
            session.commit()

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


class TestForeignKeys:
    def test_notification_log_references_valid_subscriber_and_event(
        self, session
    ) -> None:
        subscriber = Subscriber(email="fk-test@example.com")
        session.add(subscriber)
        session.commit()
        session.refresh(subscriber)

        event = Event(
            external_id="fk-evt",
            title="FK Test Event",
            url="https://example.com/fk",
        )
        session.add(event)
        session.commit()
        session.refresh(event)

        log = NotificationLog(
            subscriber_id=subscriber.id,
            event_id=event.id,
            channel="telegram",
        )
        session.add(log)
        session.commit()
        session.refresh(log)

        assert log.subscriber_id == subscriber.id
        assert log.event_id == event.id
