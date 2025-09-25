import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from fastapi import Header, HTTPException

from app.api.dependencies.auth import get_current_user, require_admin_user
from app.api.dependencies.db import get_db_session
from app.main import app
from app.models.base import Base
from app.repositories.user import UserRepository


@pytest.fixture()
def db_override():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, class_=Session)

    def _provide_session():
        with SessionLocal() as session:
            yield session

    app.dependency_overrides[get_db_session] = _provide_session

    yield SessionLocal

    app.dependency_overrides.pop(get_db_session, None)


@pytest.fixture()
def client(db_override):
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def auth_headers():
    return {"Authorization": "Bearer dummy-token"}


@pytest.fixture()
def admin_headers():
    return {"Authorization": "Bearer admin-token"}


@pytest.fixture(autouse=True)
def override_current_user(db_override):
    SessionLocal: sessionmaker = db_override  # type: ignore[assignment]

    def _mock_current_user(authorization: str | None = None):
        if authorization == "Bearer admin-token":
            with SessionLocal() as session:
                repo = UserRepository(session)
                admin = repo.create_or_update_from_auth0(
                    sub="auth0|admin",
                    email="admin@example.com",
                    name="Admin",
                )
                repo.update_user(admin, role="admin")
            return {
                "sub": "auth0|admin",
                "email": "admin@example.com",
                "name": "Admin",
            }
        with SessionLocal() as session:
            repo = UserRepository(session)
            user = repo.create_or_update_from_auth0(
                sub="auth0|user",
                email="user@example.com",
                name="Rider",
            )
            if user.timezone != "America/New_York":
                repo.update_user(user, timezone="America/New_York")
        return {
            "sub": "auth0|user",
            "email": "user@example.com",
            "name": "Rider",
            "timezone": "America/New_York",
        }

    app.dependency_overrides[get_current_user] = _mock_current_user

    def _require_admin_override(authorization: str = Header(...)):
        if authorization != "Bearer admin-token":
            raise HTTPException(status_code=403, detail="Admin privileges required")
        with SessionLocal() as session:
            repo = UserRepository(session)
            admin = repo.create_or_update_from_auth0(
                sub="auth0|admin",
                email="admin@example.com",
                name="Admin",
            )
            repo.update_user(admin, role="admin")
            session.expunge(admin)
            return admin

    app.dependency_overrides[require_admin_user] = _require_admin_override

    yield

    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(require_admin_user, None)


def test_me_endpoint_creates_and_returns_user(client, auth_headers, db_override):
    response = client.get("/v1/users/me", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["auth0_sub"] == "auth0|user"
    assert body["timezone"] == "America/New_York"


def test_update_me(client, auth_headers, db_override):
    payload = {"name": "Updated Rider", "timezone": "UTC"}
    response = client.patch("/v1/users/me", headers=auth_headers, json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Updated Rider"
    assert body["timezone"] == "UTC"


def test_admin_list_users(client, admin_headers, db_override):
    SessionLocal: sessionmaker = db_override  # type: ignore[assignment]
    with SessionLocal() as session:
        repo = UserRepository(session)
        repo.create_or_update_from_auth0(sub="auth0|user", email="user@example.com", name="User")
    response = client.get("/v1/users", headers=admin_headers)
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, list)
    assert len(body) >= 1


def test_admin_update_user(client, admin_headers, db_override):
    SessionLocal: sessionmaker = db_override  # type: ignore[assignment]
    with SessionLocal() as session:
        repo = UserRepository(session)
        user = repo.create_or_update_from_auth0(sub="auth0|user", email="user@example.com", name="User")
    response = client.patch(
        f"/v1/users/{user.id}",
        headers=admin_headers,
        json={"role": "coach", "is_active": False},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["role"] == "coach"
    assert body["is_active"] is False


def test_admin_delete_user(client, admin_headers, db_override):
    SessionLocal: sessionmaker = db_override  # type: ignore[assignment]
    with SessionLocal() as session:
        repo = UserRepository(session)
        user = repo.create_or_update_from_auth0(sub="auth0|user", email="user@example.com", name="User")
    response = client.delete(f"/v1/users/{user.id}", headers=admin_headers)
    assert response.status_code == 204
    with SessionLocal() as session:
        repo = UserRepository(session)
        stored = repo.get_by_id(user.id)
        assert stored is not None
        assert stored.is_active is False


def test_non_admin_forbidden(client, auth_headers):
    response = client.get("/v1/users", headers=auth_headers)
    assert response.status_code == 403
    assert response.json()["detail"] == "Admin privileges required"
