import json
import logging
from datetime import datetime, timedelta

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

from app.config import get_settings
from app.models import Event

log = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/calendar"]


def _get_service():
    settings = get_settings()
    if not settings.google_service_account_json:
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON not configured")
    info = json.loads(settings.google_service_account_json)
    creds = Credentials.from_service_account_info(info, scopes=SCOPES)
    return build("calendar", "v3", credentials=creds)


def _event_to_gcal_body(event: Event) -> dict:
    body: dict = {
        "summary": event.title,
        "description": event.description or "",
        "source": {"url": event.url, "title": event.title},
        "extendedProperties": {
            "private": {"datatalk_external_id": event.external_id}
        },
    }
    if event.location:
        body["location"] = event.location
    if event.date:
        body["start"] = {"dateTime": event.date.isoformat(), "timeZone": "Europe/Prague"}
        end = event.end_date or (event.date + timedelta(hours=2))
        body["end"] = {"dateTime": end.isoformat(), "timeZone": "Europe/Prague"}
    else:
        # All-day event as fallback
        today = datetime.utcnow().strftime("%Y-%m-%d")
        body["start"] = {"date": today}
        body["end"] = {"date": today}
    return body


def _find_existing_event(service, calendar_id: str, external_id: str) -> str | None:
    result = service.events().list(
        calendarId=calendar_id,
        privateExtendedProperty=f"datatalk_external_id={external_id}",
        maxResults=1,
    ).execute()
    items = result.get("items", [])
    return items[0]["id"] if items else None


def sync_events_to_google_calendar(events: list[Event]) -> int:
    settings = get_settings()
    if not settings.google_calendar_id or not settings.google_service_account_json:
        log.warning("Google Calendar not configured, skipping sync")
        return 0

    service = _get_service()
    calendar_id = settings.google_calendar_id
    synced = 0

    for event in events:
        body = _event_to_gcal_body(event)
        existing_id = _find_existing_event(service, calendar_id, event.external_id)

        if existing_id:
            service.events().update(
                calendarId=calendar_id, eventId=existing_id, body=body
            ).execute()
            log.debug(f"Updated GCal event: {event.title}")
        else:
            service.events().insert(
                calendarId=calendar_id, body=body
            ).execute()
            log.debug(f"Created GCal event: {event.title}")
        synced += 1

    log.info(f"Synced {synced} events to Google Calendar")
    return synced


def get_calendar_share_link() -> str:
    settings = get_settings()
    cal_id = settings.google_calendar_id
    return f"https://calendar.google.com/calendar/r?cid={cal_id}"
