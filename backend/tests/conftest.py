"""Shared fixtures: an isolated app per test on in-memory SQLite, plus user helpers."""

from __future__ import annotations

from collections.abc import Callable, Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from verita.api.app import create_app
from verita.core.config import Settings
from verita.db.base import Base
from verita.db.models import Role, User
from verita.services.auth import AuthService

PASSWORD = "correct-horse-battery"


@pytest.fixture
def settings() -> Settings:
    return Settings(env="test", database_url="sqlite+pysqlite:///:memory:")


@pytest.fixture
def app(settings: Settings) -> FastAPI:
    application = create_app(settings)
    Base.metadata.create_all(application.state.engine)
    return application


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def db(app: FastAPI) -> Iterator[Session]:
    session: Session = app.state.session_factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def make_user(db: Session, settings: Settings) -> Callable[..., User]:
    def _make(username: str = "priya", role: Role = Role.ANALYST, password: str = PASSWORD) -> User:
        user = AuthService(db, settings).create_user(username, password, role)
        db.commit()
        return user

    return _make


@pytest.fixture
def login(client: TestClient) -> Callable[..., str]:
    """Log in through the API; returns the CSRF token. Cookies stay on the client."""

    def _login(username: str = "priya", password: str = PASSWORD) -> str:
        response = client.post(
            "/api/v1/auth/login", json={"username": username, "password": password}
        )
        assert response.status_code == 200, response.text
        token: str = response.json()["csrf_token"]
        return token

    return _login
