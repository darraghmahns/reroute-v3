import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.base import Base
from app.models import user  # noqa: F401 ensure model registration
from app.repositories.user import UserRepository


@pytest.fixture()
def session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    with Session(engine) as db_session:
        yield db_session


def test_create_and_get_user(session: Session) -> None:
    repo = UserRepository(session)

    created = repo.create_or_update_from_auth0(
        sub="auth0|user1",
        email="rider@example.com",
        name="Rider Example",
    )

    assert created.id is not None
    assert created.auth0_sub == "auth0|user1"
    assert created.email == "rider@example.com"

    fetched = repo.get_by_auth0_sub("auth0|user1")
    assert fetched is not None
    assert fetched.id == created.id


def test_update_existing_user(session: Session) -> None:
    repo = UserRepository(session)

    repo.create_or_update_from_auth0(
        sub="auth0|user1",
        email="rider@example.com",
        name="Rider Example",
    )

    updated = repo.create_or_update_from_auth0(
        sub="auth0|user1",
        email="rider+updated@example.com",
        name="Rider Updated",
    )

    assert updated.email == "rider+updated@example.com"
    assert updated.name == "Rider Updated"

    fetched = repo.get_by_auth0_sub("auth0|user1")
    assert fetched is not None
    assert fetched.email == "rider+updated@example.com"


def test_list_and_deactivate_user(session: Session) -> None:
    repo = UserRepository(session)
    user1 = repo.create_or_update_from_auth0(
        sub="auth0|user1",
        email="user1@example.com",
        name="User One",
    )
    user2 = repo.create_or_update_from_auth0(
        sub="auth0|user2",
        email="user2@example.com",
        name="User Two",
    )

    users = repo.list_users(limit=10, offset=0)
    assert len(users) == 2

    repo.update_user(user2, role="admin", timezone="UTC")
    refreshed = repo.get_by_id(user2.id)
    assert refreshed.role == "admin"
    assert refreshed.timezone == "UTC"

    repo.deactivate_user(user1)
    inactive = repo.get_by_id(user1.id)
    assert inactive is not None
    assert inactive.is_active is False
    assert inactive.deleted_at is not None
