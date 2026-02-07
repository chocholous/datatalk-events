from datetime import datetime
from enum import StrEnum

from sqlmodel import Field, SQLModel


class SubscriberStatus(StrEnum):
    PENDING = "pending"
    VERIFIED = "verified"
    UNSUBSCRIBED = "unsubscribed"


class Subscriber(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    email: str = Field(unique=True, index=True)
    telegram_chat_id: str | None = None
    status: SubscriberStatus = SubscriberStatus.PENDING
    verification_token: str | None = None
    preferences: str = "{}"  # JSON string
    created_at: datetime = Field(default_factory=datetime.utcnow)
    verified_at: datetime | None = None


class Event(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    external_id: str = Field(unique=True, index=True)
    title: str
    date: datetime | None = None
    end_date: datetime | None = None
    location: str | None = None
    description: str | None = None
    url: str
    topics: str = "[]"  # JSON array
    event_type: str | None = None
    language: str | None = None
    scraped_at: datetime = Field(default_factory=datetime.utcnow)


class NotificationLog(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    subscriber_id: int = Field(foreign_key="subscriber.id")
    event_id: int = Field(foreign_key="event.id")
    channel: str  # email, telegram
    sent_at: datetime = Field(default_factory=datetime.utcnow)
    status: str = "sent"  # sent, failed, bounced
