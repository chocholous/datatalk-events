from datetime import datetime
from enum import StrEnum

from sqlmodel import Field, SQLModel


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
    speakers: str = "[]"  # JSON array of speaker names
    organizer: str | None = None
    image_url: str | None = None
    reminder_sent: bool = False
    scraped_at: datetime = Field(default_factory=datetime.utcnow)


class ScrapeRunStatus(StrEnum):
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"


class ScrapeRun(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    started_at: datetime = Field(default_factory=datetime.utcnow)
    finished_at: datetime | None = None
    status: ScrapeRunStatus = ScrapeRunStatus.RUNNING
    events_found: int = 0
    events_new: int = 0
    error_message: str | None = None
