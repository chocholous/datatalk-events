from collections.abc import Generator

from sqlmodel import Session

from app.database import get_session

# Will be set during app lifespan
_engine = None


def set_engine(engine):
    global _engine
    _engine = engine


def get_db() -> Generator[Session, None, None]:
    """Dependency that yields a DB session from the app engine."""
    yield from get_session(_engine)
