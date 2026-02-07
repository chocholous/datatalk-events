from collections.abc import Generator

from sqlmodel import Session, SQLModel, create_engine

from app.config import get_settings


def get_engine(database_url: str | None = None):
    url = database_url or get_settings().database_url
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    return create_engine(url, connect_args=connect_args)


def init_db(engine):
    SQLModel.metadata.create_all(engine)


def migrate_db(engine):
    """Add missing columns to existing tables (SQLite ALTER TABLE)."""
    import sqlalchemy

    inspector = sqlalchemy.inspect(engine)
    columns = {c["name"] for c in inspector.get_columns("event")}
    with engine.begin() as conn:
        if "speakers" not in columns:
            conn.execute(
                sqlalchemy.text('ALTER TABLE event ADD COLUMN speakers TEXT DEFAULT "[]"')
            )
        if "organizer" not in columns:
            conn.execute(
                sqlalchemy.text("ALTER TABLE event ADD COLUMN organizer TEXT")
            )
        if "image_url" not in columns:
            conn.execute(
                sqlalchemy.text("ALTER TABLE event ADD COLUMN image_url TEXT")
            )


def get_session(engine) -> Generator[Session, None, None]:
    """FastAPI dependency for DB session."""
    with Session(engine) as session:
        yield session
