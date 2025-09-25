from datetime import datetime, timedelta, timezone

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
def make_token() -> callable:
    secret = "test-secret"

    def _builder(sub: str, email: str = "rider@example.com", name: str = "Rider Example") -> str:
        now = datetime.now(tz=timezone.utc)
        payload = {
            "sub": sub,
            "aud": "https://api.reroute.training",
            "iss": "https://dev-example.us.auth0.com/",
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=10)).timestamp()),
            "email": email,
            "name": name,
        }
        return jwt.encode(payload, secret, algorithm="HS256")

    return _builder


@pytest.fixture(autouse=True)
def db_override():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, class_=Session)

    from app.main import app as fastapi_app

    def _provide_session():
        with SessionLocal() as session:
            yield session

    fastapi_app.dependency_overrides[get_db_session] = _provide_session

    yield SessionLocal

    fastapi_app.dependency_overrides.pop(get_db_session, None)


def test_session_creates_user(client, db_override, make_token):
    token = make_token("auth0|user1")

    response = client.post(
        "/v1/auth/session",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["auth0_sub"] == "auth0|user1"
    assert body["email"] == "rider@example.com"
    assert body["name"] == "Rider Example"
    assert body["strava_linked"] is False

    SessionLocal: sessionmaker = db_override  # type: ignore[assignment]
    with SessionLocal() as session:
        row = session.execute(text("SELECT auth0_sub FROM users")).fetchone()
        assert row is not None
        assert row.auth0_sub == "auth0|user1"


def test_session_updates_user_and_detects_strava(client, db_override, make_token):
    SessionLocal: sessionmaker = db_override  # type: ignore[assignment]
    with SessionLocal() as session:
        session.execute(
            text(
                "INSERT INTO users (auth0_sub, email, name, role, timezone, is_active, created_at, updated_at) "
                "VALUES (:sub, :email, :name, 'user', NULL, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ),
            {"sub": "auth0|user1", "email": "old@example.com", "name": "Old Name"},
        )
        session.execute(
            text(
                """
                INSERT INTO strava_credentials (
                    user_id,
                    athlete_id,
                    access_token,
                    refresh_token,
                    token_type,
                    scope,
                    expires_at
                ) VALUES (
                    1,
                    4242,
                    'access',
                    'refresh',
                    'Bearer',
                    'read',
                    CURRENT_TIMESTAMP
                )
                """
            )
        )
        session.commit()

    token = make_token("auth0|user1", email="new@example.com", name="New Name")

    response = client.post(
        "/v1/auth/session",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["email"] == "new@example.com"
    assert body["name"] == "New Name"
    assert body["strava_linked"] is True

    with SessionLocal() as session:
        row = session.execute(text("SELECT email, name FROM users WHERE auth0_sub='auth0|user1'"))
        updated = row.fetchone()
        assert updated.email == "new@example.com"
        assert updated.name == "New Name"


def test_session_requires_auth(client):
    response = client.post("/v1/auth/session")
    assert response.status_code == 401
