from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import strava as strava_models  # noqa: F401 ensure registration
from app.models import user as user_models  # noqa: F401 ensure registration
from app.models.base import Base
from app.repositories.strava import StravaCredentialRepository
from app.repositories.user import UserRepository


@pytest.fixture()
def session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    with Session(engine) as db_session:
        yield db_session


@pytest.fixture()
def user(session: Session):
    repo = UserRepository(session)
    return repo.create_or_update_from_auth0(sub="auth0|1", email="user@example.com", name="User")


def test_upsert_credentials(session: Session, user) -> None:  # type: ignore[override]
    repo = StravaCredentialRepository(session)
    expires_at = datetime.now(tz=timezone.utc) + timedelta(hours=6)

    stored = repo.upsert_from_token_exchange(
        user_id=user.id,
        athlete_id=4242,
        access_token="access",
        refresh_token="refresh",
        token_type="Bearer",
        scope=["read", "activity:read_all"],
        expires_at=expires_at,
    )

    assert stored.id is not None
    assert stored.user_id == user.id
    assert stored.athlete_id == 4242
    assert stored.scope == "read,activity:read_all"

    fetched = repo.get_by_user_id(user.id)
    assert fetched is not None
    assert fetched.access_token == "access"

    new_expiry = expires_at + timedelta(hours=1)

    updated = repo.upsert_from_token_exchange(
        user_id=user.id,
        athlete_id=4242,
        access_token="access2",
        refresh_token="refresh2",
        token_type="Bearer",
        scope=["read"],
        expires_at=new_expiry,
    )

    assert updated.access_token == "access2"
    assert updated.scope == "read"
    assert repo.get_by_user_id(user.id).expires_at == new_expiry


def test_get_by_athlete_id(session: Session, user) -> None:  # type: ignore[override]
    repo = StravaCredentialRepository(session)
    expires_at = datetime.now(tz=timezone.utc)
    repo.upsert_from_token_exchange(
        user_id=user.id,
        athlete_id=999,
        access_token="a",
        refresh_token="r",
        token_type="Bearer",
        scope=["read"],
        expires_at=expires_at,
    )

    fetched = repo.get_by_athlete_id(999)
    assert fetched is not None
    assert fetched.user_id == user.id
