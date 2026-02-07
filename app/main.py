import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from sqlmodel import Session, select

from app.config import get_settings
from app.database import get_engine, get_session, init_db
from app.models import Subscriber  # noqa: F401 — ensure table is registered
from app.scheduler import create_scheduler

log = logging.getLogger(__name__)


async def scheduled_scrape() -> None:
    """Placeholder for scheduled scrape job. Full pipeline comes in Phase 5."""
    log.info("Scheduled scrape triggered")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Startup: create engine and initialize database
    engine = get_engine()
    init_db(engine)
    app.state.engine = engine

    # Start scheduler
    scheduler = create_scheduler(scheduled_scrape)
    scheduler.start()
    app.state.scheduler = scheduler
    log.info("Scheduler started")

    yield

    # Shutdown: stop scheduler and dispose engine
    scheduler.shutdown(wait=False)
    log.info("Scheduler stopped")
    engine.dispose()


settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    debug=settings.debug,
    lifespan=lifespan,
)


def get_db():
    """Dependency that yields a DB session from the app engine."""
    yield from get_session(app.state.engine)


@app.get("/")
async def root() -> dict[str, str]:
    return {"app": settings.app_name, "status": "running"}


@app.get("/health")
def health(db: Session = Depends(get_db)) -> dict[str, str]:
    db.exec(select(Subscriber).limit(1))
    return {"status": "healthy", "db": "connected"}
