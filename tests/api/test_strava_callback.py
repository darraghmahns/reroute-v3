from datetime import datetime, timedelta, timezone

import httpx
import pytest
from jose import jwt
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.dependencies.db import get_db_session
from app.models import strava as strava_models  # noqa: F401 ensure registration
from app.models import user as user_models  # noqa: F401 ensure registration
from app.models.base import Base


@pytest.fixture()
def state_token() -> str:
    return "0123456789abcdef0123456789abcdef"


@pytest.fixture(autouse=True)
def session_factory():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, class_=Session)

    from app.main import app as fastapi_app

    def _override_session():
        with SessionLocal() as session:
            yield session

    fastapi_app.dependency_overrides[get_db_session] = _override_session

    try:
        yield SessionLocal
    finally:
        fastapi_app.dependency_overrides.pop(get_db_session, None)


def _build_token(sub: str) -> str:
    now = datetime.now(tz=timezone.utc)
    payload = {
        "sub": sub,
        "aud": "https://api.reroute.training",
        "iss": "https://dev-example.us.auth0.com/",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=10)).timestamp()),
        "email": "rider@example.com",
        "name": "Rider Example",
    }
    return jwt.encode(payload, "test-secret", algorithm="HS256")


def _auth_headers(sub: str) -> dict[str, str]:
    token = _build_token(sub)
    return {"Authorization": f"Bearer {token}"}


def test_strava_callback_success(client, session_factory, monkeypatch, state_token):
    def fake_post(url: str, data: dict, timeout: float) -> httpx.Response:  # type: ignore[override]
        assert url == "https://www.strava.com/oauth/token"
        assert data["code"] == "auth_code"
        request = httpx.Request("POST", url)
        return httpx.Response(
            200,
            json={
                "access_token": "access123",
                "refresh_token": "refresh123",
                "expires_at": 1_700_000_000,
                "token_type": "Bearer",
                "scope": "read,activity:read_all",
                "athlete": {"id": 4242, "firstname": "A", "lastname": "Rider"},
            },
            request=request,
        )

    monkeypatch.setattr("app.services.strava.httpx.post", fake_post)

    client.cookies.clear()
    client.cookies.set("strava_oauth_state", state_token)

    response = client.get(
        "/v1/integrations/strava/callback",
        params={"code": "auth_code", "state": state_token},
        headers=_auth_headers("auth0|user123"),
    )

    assert response.status_code == 200

    body = response.json()
    assert body["athlete_id"] == 4242
    assert body["scope"] == ["read", "activity:read_all"]

    expires_at = datetime.fromisoformat(body["expires_at"].replace("Z", "+00:00"))
    assert expires_at == datetime.fromtimestamp(1_700_000_000, tz=timezone.utc)

    session_maker = session_factory
    with session_maker() as session:
        credential = session.execute(
            text(
                "SELECT access_token, refresh_token, athlete_id FROM strava_credentials"
            )
        ).fetchone()
        assert credential is not None
        assert credential.access_token == "access123"
        assert credential.refresh_token == "refresh123"
        assert credential.athlete_id == 4242

        user = session.execute(text("SELECT auth0_sub FROM users")).fetchone()
        assert user.auth0_sub == "auth0|user123"


def test_strava_callback_requires_auth(client, state_token):
    client.cookies.clear()
    client.cookies.set("strava_oauth_state", state_token)

    response = client.get(
        "/v1/integrations/strava/callback",
        params={"code": "auth_code", "state": state_token},
    )

    assert response.status_code == 401


def test_strava_callback_missing_cookie(client, state_token):
    client.cookies.clear()

    response = client.get(
        "/v1/integrations/strava/callback",
        params={"code": "auth_code", "state": state_token},
        headers=_auth_headers("auth0|user123"),
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Missing state cookie"


def test_strava_callback_state_mismatch(client, state_token):
    client.cookies.clear()
    client.cookies.set("strava_oauth_state", state_token)

    response = client.get(
        "/v1/integrations/strava/callback",
        params={"code": "auth_code", "state": "badstate"},
        headers=_auth_headers("auth0|user123"),
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "State mismatch"


def test_strava_callback_missing_code(client, state_token):
    client.cookies.clear()
    client.cookies.set("strava_oauth_state", state_token)

    response = client.get(
        "/v1/integrations/strava/callback",
        params={"state": state_token},
        headers=_auth_headers("auth0|user123"),
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Missing code"


def test_strava_callback_handles_strava_error(client, session_factory, monkeypatch, state_token):
    def fake_post(url: str, data: dict, timeout: float) -> httpx.Response:  # type: ignore[override]
        request = httpx.Request("POST", url)
        return httpx.Response(401, json={"message": "bad code"}, request=request)

    monkeypatch.setattr("app.services.strava.httpx.post", fake_post)

    client.cookies.clear()
    client.cookies.set("strava_oauth_state", state_token)

    response = client.get(
        "/v1/integrations/strava/callback",
        params={"code": "auth_code", "state": state_token},
        headers=_auth_headers("auth0|user123"),
    )

    assert response.status_code == 502
    assert response.json()["detail"] == "Strava token exchange failed"
