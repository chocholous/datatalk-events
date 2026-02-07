import asyncio

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import Response
from sqlmodel import Session, select

from app.dependencies import get_db
from app.ical import event_to_ical
from app.models import Event
from app.notifications.pipeline import run_scrape_and_notify

router = APIRouter()


@router.get("/events")
def list_events(limit: int = 20, db: Session = Depends(get_db)):
    events = db.exec(
        select(Event).order_by(Event.scraped_at.desc()).limit(limit)
    ).all()
    return events


@router.get("/events/{event_id}/ical")
def get_event_ical(event_id: int, db: Session = Depends(get_db)):
    event = db.get(Event, event_id)
    if not event:
        raise HTTPException(404, "Event not found")
    ical_data = event_to_ical(event)
    return Response(
        content=ical_data,
        media_type="text/calendar",
        headers={"Content-Disposition": f'attachment; filename="event-{event_id}.ics"'},
    )


def _run_pipeline(db: Session) -> None:
    """Run the async pipeline in a new event loop for background tasks."""
    asyncio.run(run_scrape_and_notify(db))


@router.post("/scrape")
def trigger_scrape(background: BackgroundTasks, db: Session = Depends(get_db)):
    background.add_task(_run_pipeline, db)
    return {"success": True, "message": "Scraping started"}
