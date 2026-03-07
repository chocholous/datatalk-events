import hashlib
import json
import logging
from datetime import datetime, timedelta

from sqlmodel import Session, select

from app.detail_fetcher import DetailFetcher
from app.extractor import EventExtractor
from app.google_calendar import sync_events_to_google_calendar
from app.models import Event, ScrapeRun, ScrapeRunStatus
from app.notifications.telegram import TelegramNotifier, format_event_reminder
from app.scraper import Scraper

log = logging.getLogger(__name__)


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None


def _ensure_list(value) -> list:
    if isinstance(value, list):
        return value
    return [value] if value else []


def _ensure_str_or_none(value) -> str | None:
    if isinstance(value, list):
        return ", ".join(str(o) for o in value) if value else None
    return value


async def run_scrape_and_sync(session: Session) -> None:
    run = ScrapeRun(status=ScrapeRunStatus.RUNNING)
    session.add(run)
    session.commit()
    session.refresh(run)

    try:
        scraper = Scraper()
        detail_fetcher = DetailFetcher()
        extractor = EventExtractor()

        # 1. Scrape
        raw_events = await scraper.scrape()
        if not raw_events:
            log.warning("No events found")
            run.events_found = 0
            run.status = ScrapeRunStatus.SUCCESS
            run.finished_at = datetime.utcnow()
            session.commit()
            return

        # 1.5 Fetch detail pages
        enriched_raw = await detail_fetcher.fetch_details(raw_events)

        # 2. LLM extraction
        enriched = await extractor.extract(enriched_raw)

        # 3. Upsert events
        new_count = 0
        updated_count = 0
        all_events: list[Event] = []
        for e in enriched:
            url = e.get("url", "")
            ext_id = hashlib.md5(url.encode()).hexdigest()[:16]

            topics = json.dumps(_ensure_list(e.get("topics", [])))
            speakers = json.dumps(_ensure_list(e.get("speakers", [])))
            organizer = _ensure_str_or_none(e.get("organizer"))

            existing = session.exec(
                select(Event).where(Event.external_id == ext_id)
            ).first()

            if existing:
                existing.title = e.get("title", "")
                existing.url = url
                existing.date = _parse_date(e.get("date"))
                existing.end_date = _parse_date(e.get("end_date"))
                existing.location = e.get("location")
                existing.description = e.get("description")
                existing.topics = topics
                existing.event_type = e.get("type")
                existing.language = e.get("language")
                existing.speakers = speakers
                existing.organizer = organizer
                existing.image_url = e.get("image_url")
                existing.scraped_at = datetime.utcnow()
                all_events.append(existing)
                updated_count += 1
            else:
                event = Event(
                    external_id=ext_id,
                    title=e.get("title", ""),
                    url=url,
                    date=_parse_date(e.get("date")),
                    end_date=_parse_date(e.get("end_date")),
                    location=e.get("location"),
                    description=e.get("description"),
                    topics=topics,
                    event_type=e.get("type"),
                    language=e.get("language"),
                    speakers=speakers,
                    organizer=organizer,
                    image_url=e.get("image_url"),
                )
                session.add(event)
                all_events.append(event)
                new_count += 1
        session.commit()

        for ev in all_events:
            session.refresh(ev)

        run.events_found = len(enriched)
        run.events_new = new_count
        log.info(f"Events: {new_count} new, {updated_count} updated")

        # 4. Sync to Google Calendar
        try:
            sync_events_to_google_calendar(all_events)
        except Exception as exc:
            log.error(f"Google Calendar sync failed: {exc}")

        run.status = ScrapeRunStatus.SUCCESS
        run.finished_at = datetime.utcnow()
        session.commit()
    except Exception as exc:
        run.status = ScrapeRunStatus.FAILED
        run.finished_at = datetime.utcnow()
        run.error_message = str(exc)
        session.commit()
        raise


async def send_event_reminders(session: Session) -> None:
    """Send Telegram reminder to channel for events starting in ~2 hours."""
    now = datetime.utcnow()
    window_start = now + timedelta(hours=1, minutes=45)
    window_end = now + timedelta(hours=2, minutes=15)

    upcoming = session.exec(
        select(Event).where(Event.date >= window_start, Event.date <= window_end)
    ).all()

    if not upcoming:
        return

    telegram = TelegramNotifier()
    text = format_event_reminder(list(upcoming))
    if await telegram.send_to_channel(text):
        log.info(f"Sent reminder for {len(upcoming)} events starting in ~2h")
    else:
        log.warning("Failed to send reminder to channel")
