import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import database
from app.main import create_app


@pytest.fixture
def test_engine(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'test.db'}",
        connect_args={"check_same_thread": False},
    )
    database.Base.metadata.create_all(bind=engine)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def test_session_factory(test_engine, monkeypatch):
    session_factory = sessionmaker(
        bind=test_engine,
        autoflush=False,
        autocommit=False,
    )
    monkeypatch.setattr(database, "SessionLocal", session_factory)
    return session_factory


@pytest.fixture
def test_app(test_engine, test_session_factory):
    app = create_app(test_engine)

    def override_get_session():
        yield from database.get_session()

    app.dependency_overrides[database.get_session] = override_get_session
    try:
        yield app
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def client(test_app):
    with TestClient(test_app) as test_client:
        yield test_client