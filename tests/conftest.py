from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("FRONTEND_BASE_URL", "https://frontend.example")

    monkeypatch.setenv("STRAVA_CLIENT_ID", "12345")
    monkeypatch.setenv("STRAVA_CLIENT_SECRET", "secret")
    monkeypatch.setenv("STRAVA_REDIRECT_URI", "https://example.com/strava/callback")

    monkeypatch.setenv("AUTH0_DOMAIN", "dev-example.us.auth0.com")
    monkeypatch.setenv("AUTH0_AUDIENCE", "https://api.reroute.training")
    monkeypatch.setenv("AUTH0_CLIENT_SECRET", "test-secret")
    monkeypatch.setenv("AUTH0_ALGORITHMS", '["HS256"]')
    monkeypatch.setenv("AUTH0_JWKS_CACHE_TTL", "5")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///./test.db")


@pytest.fixture()
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client
