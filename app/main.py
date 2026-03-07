import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from sqlmodel import Session, select

from app.config import get_settings
from app.database import get_engine, init_db, migrate_db
from app.dependencies import get_db, set_engine
from app.models import Subscriber, ScrapeRun  # noqa: F401 — ensure tables are registered
from app.notifications.pipeline import run_scrape_and_notify, send_daily_reminders
from app.routers import admin, events, subscribers
from app.scheduler import create_scheduler

log = logging.getLogger(__name__)


async def scheduled_scrape() -> None:
    from app.dependencies import _engine

    if _engine is None:
        log.error("Engine not initialized, skipping scheduled scrape")
        return
    with Session(_engine) as session:
        await run_scrape_and_notify(session)


async def scheduled_daily_reminder() -> None:
    from app.dependencies import _engine

    if _engine is None:
        log.error("Engine not initialized, skipping daily reminder")
        return
    with Session(_engine) as session:
        await send_daily_reminders(session)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    engine = get_engine()
    init_db(engine)
    migrate_db(engine)
    app.state.engine = engine
    set_engine(engine)

    scheduler = create_scheduler(scheduled_scrape, scheduled_daily_reminder)
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

app.include_router(subscribers.router)
app.include_router(events.router)
app.include_router(admin.router)


@app.get("/")
async def root() -> dict[str, str]:
    return {"app": settings.app_name, "status": "running"}


@app.get("/health")
def health(db: Session = Depends(get_db)) -> dict[str, str]:
    db.exec(select(Subscriber).limit(1))
    return {"status": "healthy", "db": "connected"}
