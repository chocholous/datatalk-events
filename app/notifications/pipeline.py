import hashlib
import json
import logging
from datetime import datetime

from sqlmodel import Session, select

from app.detail_fetcher import DetailFetcher
from app.extractor import EventExtractor
from app.models import Event, NotificationLog, ScrapeRun, ScrapeRunStatus, Subscriber, SubscriberStatus
from app.notifications.email import get_email_sender, make_ics_attachment
from app.notifications.telegram import TelegramNotifier, format_telegram_message
from app.scraper import Scraper

log = logging.getLogger(__name__)


def _parse_date(value: str | None) -> datetime | None:
    """Parse an ISO date/datetime string, returning None on failure."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None


def _ensure_list(value) -> list:
    """Ensure value is a list (handles None, string, other types)."""
    if isinstance(value, list):
        return value
    return [value] if value else []


def _ensure_str_or_none(value) -> str | None:
    """Convert list to comma-separated string, pass through str/None."""
    if isinstance(value, list):
        return ", ".join(str(o) for o in value) if value else None
    return value


async def run_scrape_and_notify(session: Session) -> None:
    run = ScrapeRun(status=ScrapeRunStatus.RUNNING)
    session.add(run)
    session.commit()
    session.refresh(run)

    try:
        scraper = Scraper()
        detail_fetcher = DetailFetcher()
        extractor = EventExtractor()
        email_sender = get_email_sender()
        telegram = TelegramNotifier()

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

        # 3. Upsert events (update existing by external_id, insert new)
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
                # Update existing event with fresh data
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

        # Refresh to get IDs
        for ev in all_events:
            session.refresh(ev)

        run.events_found = len(enriched)
        run.events_new = new_count
        log.info(f"Events: {new_count} new, {updated_count} updated")

        # 4. Notify subscribers about upcoming events they haven't been notified about
        now = datetime.utcnow()
        upcoming = [ev for ev in all_events if ev.date is None or ev.date > now]

        if not upcoming:
            log.info("No upcoming events to notify about")
            run.status = ScrapeRunStatus.SUCCESS
            run.finished_at = datetime.utcnow()
            session.commit()
            return

        subscribers = session.exec(
            select(Subscriber).where(Subscriber.status == SubscriberStatus.VERIFIED)
        ).all()

        total_notifications = 0
        for sub in subscribers:
            # Find events this subscriber hasn't been notified about yet
            notif_logs = session.exec(
                select(NotificationLog).where(
                    NotificationLog.subscriber_id == sub.id,
                    NotificationLog.channel == "email",
                )
            ).all()
            already_notified = {nl.event_id for nl in notif_logs}
            to_notify = [ev for ev in upcoming if ev.id not in already_notified]

            if not to_notify:
                continue

            # Email with .ics attachments
            attachments = [make_ics_attachment(ev) for ev in to_notify]
            html = format_event_email(to_notify)
            await email_sender.send(
                sub.email, "Nove eventy na DataTalk", html, attachments
            )

            # Telegram
            if sub.telegram_chat_id:
                text = format_telegram_message(to_notify)
                await telegram.send_message(sub.telegram_chat_id, text)

            # Log notifications
            for ev in to_notify:
                session.add(
                    NotificationLog(
                        subscriber_id=sub.id, event_id=ev.id, channel="email"
                    )
                )
                if sub.telegram_chat_id:
                    session.add(
                        NotificationLog(
                            subscriber_id=sub.id, event_id=ev.id, channel="telegram"
                        )
                    )
            total_notifications += len(to_notify)

        run.status = ScrapeRunStatus.SUCCESS
        run.finished_at = datetime.utcnow()
        session.commit()
        log.info(
            f"Notified {len(subscribers)} subscribers about {total_notifications} event notifications total"
        )
    except Exception as exc:
        run.status = ScrapeRunStatus.FAILED
        run.finished_at = datetime.utcnow()
        run.error_message = str(exc)
        session.commit()
        raise


def format_event_email(events: list[Event]) -> str:
    items = []
    for e in events:
        speakers_list = json.loads(e.speakers) if e.speakers else []
        speakers_html = ""
        if speakers_list:
            speakers_html = (
                f'<p style="color:#444;margin:5px 0;font-size:0.9em;">'
                f'Speakers: {", ".join(speakers_list)}</p>'
            )
        desc_html = ""
        if e.description:
            desc_html = (
                f'<p style="color:#555;margin:5px 0;font-size:0.9em;">'
                f"{e.description}</p>"
            )
        items.append(
            f'<div style="margin-bottom:20px;padding:15px;border:1px solid #ddd;border-radius:8px;">'
            f'<h3 style="margin:0 0 10px 0;">{e.title}</h3>'
            f'<p style="color:#666;margin:5px 0;">{e.location or "TBD"}</p>'
            f"{speakers_html}"
            f"{desc_html}"
            f'<a href="{e.url}" style="color:#0066cc;">Vice info</a>'
            f"</div>"
        )
    return (
        f'<div style="font-family:sans-serif;max-width:600px;margin:0 auto;">'
        f'<h1 style="color:#333;">Nove eventy tento tyden</h1>'
        f'{"".join(items)}'
        f"</div>"
    )
