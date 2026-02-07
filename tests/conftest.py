import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.dependencies import get_db
from app.main import app


@pytest.fixture(name="engine")
def engine_fixture():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture(name="session")
def session_fixture(engine):
    with Session(engine) as session:
        yield session
        session.rollback()


@pytest.fixture(name="client")
def client_fixture(session):
    def _get_db_override():
        yield session

    app.dependency_overrides[get_db] = _get_db_override
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()
