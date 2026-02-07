import hashlib
import json
import logging
from datetime import datetime

from sqlmodel import Session, delete, select

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

        # Delete previous events (fresh start each run)
        session.exec(delete(Event))
        session.commit()

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

        # 3. Save events
        new_events: list[Event] = []
        for e in enriched:
            url = e.get("url", "")
            event_id = hashlib.md5(url.encode()).hexdigest()[:16]
            event = Event(
                external_id=event_id,
                title=e.get("title", ""),
                url=url,
                date=_parse_date(e.get("date")),
                end_date=_parse_date(e.get("end_date")),
                location=e.get("location"),
                description=e.get("description"),
                topics=json.dumps(e.get("topics", [])),
                event_type=e.get("type"),
                language=e.get("language"),
                speakers=json.dumps(e.get("speakers", [])),
                organizer=e.get("organizer"),
                image_url=e.get("image_url"),
            )
            session.add(event)
            new_events.append(event)
        session.commit()

        run.events_found = len(enriched)
        run.events_new = len(new_events)

        if not new_events:
            log.info("No new events to notify about")
            run.status = ScrapeRunStatus.SUCCESS
            run.finished_at = datetime.utcnow()
            session.commit()
            return

        # Refresh to get IDs
        for ev in new_events:
            session.refresh(ev)

        # 4. Notify verified subscribers
        subscribers = session.exec(
            select(Subscriber).where(Subscriber.status == SubscriberStatus.VERIFIED)
        ).all()

        for sub in subscribers:
            # Email with .ics attachments
            attachments = [make_ics_attachment(ev) for ev in new_events]
            html = format_event_email(new_events)
            await email_sender.send(
                sub.email, "Nove eventy na DataTalk", html, attachments
            )

            # Telegram
            if sub.telegram_chat_id:
                text = format_telegram_message(new_events)
                await telegram.send_message(sub.telegram_chat_id, text)

            # Log notifications
            for ev in new_events:
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

        run.status = ScrapeRunStatus.SUCCESS
        run.finished_at = datetime.utcnow()
        session.commit()
        log.info(
            f"Notified {len(subscribers)} subscribers about {len(new_events)} new events"
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
