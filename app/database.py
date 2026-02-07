from collections.abc import Generator

from sqlmodel import Session, SQLModel, create_engine

from app.config import get_settings


def get_engine(database_url: str | None = None):
    url = database_url or get_settings().database_url
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    return create_engine(url, connect_args=connect_args)


def init_db(engine):
    SQLModel.metadata.create_all(engine)


def get_session(engine) -> Generator[Session, None, None]:
    """FastAPI dependency for DB session."""
    with Session(engine) as session:
        yield session
