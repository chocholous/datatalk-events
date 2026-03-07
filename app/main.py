import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from app.config import get_settings
from app.database import get_engine, init_db, migrate_db
from app.dependencies import get_db, set_engine
from app.google_calendar import get_calendar_share_link
from app.models import Event, ScrapeRun  # noqa: F401 — ensure tables are registered
from app.notifications.pipeline import run_scrape_and_sync, send_event_reminders
from app.routers import admin, events
from app.scheduler import create_scheduler

log = logging.getLogger(__name__)


async def scheduled_scrape() -> None:
    from app.dependencies import _engine

    if _engine is None:
        log.error("Engine not initialized, skipping scheduled scrape")
        return
    with Session(_engine) as session:
        await run_scrape_and_sync(session)


async def scheduled_event_reminder() -> None:
    from app.dependencies import _engine

    if _engine is None:
        log.error("Engine not initialized, skipping event reminder")
        return
    with Session(_engine) as session:
        await send_event_reminders(session)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    engine = get_engine()
    init_db(engine)
    migrate_db(engine)
    app.state.engine = engine
    set_engine(engine)

    scheduler = create_scheduler(scheduled_scrape, scheduled_event_reminder)
    scheduler.start()
    app.state.scheduler = scheduler
    log.info("Scheduler started")

    yield

    scheduler.shutdown(wait=False)
    log.info("Scheduler stopped")
    engine.dispose()


settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    debug=settings.debug,
    lifespan=lifespan,
)

app.include_router(events.router)
app.include_router(admin.router)

templates = Jinja2Templates(directory="app/templates")


@app.get("/", response_class=HTMLResponse)
def landing(request: Request, db: Session = Depends(get_db)):
    now = datetime.utcnow()
    upcoming = db.exec(
        select(Event).where(Event.date >= now).order_by(Event.date).limit(20)
    ).all()
    calendar_link = get_calendar_share_link() if settings.google_calendar_id else None
    telegram_link = f"https://t.me/{settings.telegram_channel_id.lstrip('@')}" if settings.telegram_channel_id else None
    return templates.TemplateResponse(
        "subscribe.html",
        {"request": request, "events": upcoming, "calendar_link": calendar_link, "telegram_link": telegram_link},
    )


@app.get("/api/status")
async def api_status() -> dict[str, str]:
    return {"app": settings.app_name, "status": "running"}


@app.get("/health")
def health(db: Session = Depends(get_db)) -> dict[str, str]:
    db.exec(select(Event).limit(1))
    return {"status": "healthy", "db": "connected"}
