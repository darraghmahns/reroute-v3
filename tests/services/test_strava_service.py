from datetime import datetime, timedelta, timezone
from typing import Any, Callable

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import strava as strava_models  # noqa: F401 ensure registration
from app.models import user as user_models  # noqa: F401 ensure registration
from app.models.base import Base
from app.repositories.strava import StravaCredentialRepository
from app.repositories.user import UserRepository
from app.schemas.strava import StravaTokenExchangeResponse
from app.services.strava import StravaAuthService
from app.services.strava_api import StravaActivityService, StravaAPIError
from app.core.config import Settings


class DummyAuthService(StravaAuthService):
    def __init__(self, settings: Settings):
        super().__init__(settings)
        self.refresh_calls: list[str] = []
        self._next_exchange: StravaTokenExchangeResponse | None = None

    def set_next_exchange(self, exchange: StravaTokenExchangeResponse) -> None:
        self._next_exchange = exchange

    def refresh_access_token(  # type: ignore[override]
        self,
        refresh_token: str,
        *,
        athlete_id: int | None = None,
    ) -> StravaTokenExchangeResponse:
        self.refresh_calls.append(refresh_token)
        if not self._next_exchange:
            raise AssertionError("No exchange prepared")
        exchange = self._next_exchange
        self._next_exchange = None
        return exchange


class FakeRequester:
    def __init__(self, responses: list[httpx.Response]):
        self._responses = responses
        self.calls: list[dict[str, Any]] = []

    def __call__(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> httpx.Response:
        self.calls.append({"method": method, "url": url, "headers": headers, "params": params})
        if not self._responses:
            raise AssertionError("No more fake responses queued")
        return self._responses.pop(0)


@pytest.fixture()
def session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    with Session(engine) as db_session:
        yield db_session


@pytest.fixture()
def settings() -> Settings:
    return Settings(
        app_env="test",
        frontend_base_url="https://frontend.example",
        database_url="sqlite:///./dev.db",
        strava_client_id="client",
        strava_client_secret="secret",
        strava_redirect_uri="https://example.com/callback",
        auth0_domain="dev-example.us.auth0.com",
        auth0_audience="https://api.reroute.training",
        auth0_client_secret="auth0-secret",
    )


def _create_user_and_credential(session: Session) -> tuple[int, StravaCredentialRepository]:
    user_repo = UserRepository(session)
    user = user_repo.create_or_update_from_auth0(sub="auth0|user", email="rider@example.com", name="Rider")
    repo = StravaCredentialRepository(session)
    repo.upsert_from_token_exchange(
        user_id=user.id,
        athlete_id=4242,
        access_token="access",
        refresh_token="refresh",
        token_type="Bearer",
        scope=["read"],
        expires_at=datetime.now(tz=timezone.utc) + timedelta(hours=2),
    )
    return user.id, repo


def _make_response(status: int, json_body: Any | None = None, headers: dict[str, str] | None = None) -> httpx.Response:
    return httpx.Response(
        status,
        json=json_body,
        headers=headers,
        request=httpx.Request("GET", "https://www.strava.com/api/v3/athlete/activities"),
    )


def _make_exchange(access_token: str, refresh_token: str, expires_in_minutes: int = 60) -> StravaTokenExchangeResponse:
    expires_at = datetime.now(tz=timezone.utc) + timedelta(minutes=expires_in_minutes)
    return StravaTokenExchangeResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="Bearer",
        scope=["read"],
        expires_at=expires_at,
        athlete_id=4242,
    )


def _build_service(
    settings: Settings,
    repo: StravaCredentialRepository,
    auth_service: DummyAuthService,
    requester: Callable[..., httpx.Response],
    sleeper: Callable[[float], None] | None = None,
) -> StravaActivityService:
    return StravaActivityService(
        settings=settings,
        credential_repo=repo,
        auth_service=auth_service,
        request_func=requester,
        sleep=sleeper or (lambda _: None),
    )


def test_list_activities_returns_data(session: Session, settings: Settings) -> None:
    user_id, repo = _create_user_and_credential(session)
    auth_service = DummyAuthService(settings)
    requester = FakeRequester([
        _make_response(200, json_body=[{"id": 1, "name": "Ride"}]),
    ])

    service = _build_service(settings, repo, auth_service, requester)

    activities = service.list_activities(user_id=user_id, page=2, per_page=50)

    assert activities == [{"id": 1, "name": "Ride"}]
    assert requester.calls[0]["params"] == {"page": 2, "per_page": 50}
    assert requester.calls[0]["headers"]["Authorization"].startswith("Bearer ")
    assert auth_service.refresh_calls == []


def test_list_activities_refreshes_when_expired(session: Session, settings: Settings) -> None:
    user_id, repo = _create_user_and_credential(session)
    credential = repo.get_by_user_id(user_id)
    assert credential is not None
    credential.expires_at = datetime.now(tz=timezone.utc) - timedelta(minutes=5)
    session.commit()

    auth_service = DummyAuthService(settings)
    auth_service.set_next_exchange(_make_exchange("access2", "refresh2"))

    requester = FakeRequester([
        _make_response(200, json_body=[]),
    ])

    service = _build_service(settings, repo, auth_service, requester)

    service.list_activities(user_id=user_id)

    assert auth_service.refresh_calls == ["refresh"]
    updated = repo.get_by_user_id(user_id)
    assert updated.access_token == "access2"


def test_list_activities_refreshes_on_unauthorized(session: Session, settings: Settings) -> None:
    user_id, repo = _create_user_and_credential(session)

    auth_service = DummyAuthService(settings)
    auth_service.set_next_exchange(_make_exchange("access2", "refresh2"))

    requester = FakeRequester(
        [
            _make_response(401),
            _make_response(200, json_body=[{"id": 2}]),
        ]
    )

    service = _build_service(settings, repo, auth_service, requester)

    activities = service.list_activities(user_id=user_id)

    assert activities == [{"id": 2}]
    assert len(auth_service.refresh_calls) == 1
    assert len(requester.calls) == 2
    updated = repo.get_by_user_id(user_id)
    assert updated.access_token == "access2"


def test_list_activities_retries_on_rate_limit(session: Session, settings: Settings) -> None:
    user_id, repo = _create_user_and_credential(session)
    auth_service = DummyAuthService(settings)
    sleep_calls: list[float] = []

    requester = FakeRequester(
        [
            _make_response(429, headers={"Retry-After": "0"}),
            _make_response(200, json_body=[{"id": 3}]),
        ]
    )

    service = _build_service(
        settings,
        repo,
        auth_service,
        requester,
        sleeper=lambda seconds: sleep_calls.append(seconds),
    )

    activities = service.list_activities(user_id=user_id)

    assert activities == [{"id": 3}]
    assert sleep_calls == [0.0]


def test_list_activities_requires_linked_account(session: Session, settings: Settings) -> None:
    repo = StravaCredentialRepository(session)
    auth_service = DummyAuthService(settings)
    requester = FakeRequester([])
    service = _build_service(settings, repo, auth_service, requester)

    with pytest.raises(StravaAPIError) as exc:
        service.list_activities(user_id=999)

    assert exc.value.status_code == 404


def test_get_activity_returns_detail(session: Session, settings: Settings) -> None:
    user_id, repo = _create_user_and_credential(session)
    auth_service = DummyAuthService(settings)
    requester = FakeRequester([
        _make_response(200, json_body={"id": 1, "name": "Ride"}),
    ])

    service = _build_service(settings, repo, auth_service, requester)

    detail = service.get_activity(user_id=user_id, activity_id=1, include_all_efforts=True)

    assert detail["id"] == 1
    assert requester.calls[0]["params"] == {"include_all_efforts": "true"}


def test_get_activity_refreshes_on_unauthorized(session: Session, settings: Settings) -> None:
    user_id, repo = _create_user_and_credential(session)
    auth_service = DummyAuthService(settings)
    auth_service.set_next_exchange(_make_exchange("access2", "refresh2"))

    requester = FakeRequester([
        _make_response(401),
        _make_response(200, json_body={"id": 2}),
    ])

    service = _build_service(settings, repo, auth_service, requester)

    detail = service.get_activity(user_id=user_id, activity_id=2)

    assert detail["id"] == 2
    assert len(requester.calls) == 2
    assert auth_service.refresh_calls == ["refresh"]


def test_get_activity_not_linked(session: Session, settings: Settings) -> None:
    repo = StravaCredentialRepository(session)
    auth_service = DummyAuthService(settings)
    service = _build_service(settings, repo, auth_service, FakeRequester([]))

    with pytest.raises(StravaAPIError) as exc:
        service.get_activity(user_id=999, activity_id=1)

    assert exc.value.status_code == 404


def test_get_activity_streams(session: Session, settings: Settings) -> None:
    user_id, repo = _create_user_and_credential(session)
    auth_service = DummyAuthService(settings)
    requester = FakeRequester([
        _make_response(200, json_body={"latlng": {"type": "latlng", "data": []}}),
    ])

    service = _build_service(settings, repo, auth_service, requester)

    streams = service.get_activity_streams(user_id=user_id, activity_id=1, keys=["latlng", "time"], key_by_type=True)

    assert "latlng" in streams
    assert requester.calls[0]["params"] == {"keys": "latlng,time", "key_by_type": "true"}


def test_get_activity_streams_not_found(session: Session, settings: Settings) -> None:
    user_id, repo = _create_user_and_credential(session)
    auth_service = DummyAuthService(settings)
    requester = FakeRequester([
        _make_response(404),
    ])

    service = _build_service(settings, repo, auth_service, requester)

    with pytest.raises(StravaAPIError) as exc:
        service.get_activity_streams(user_id=user_id, activity_id=999, keys=["watts"])

    assert exc.value.status_code == 404

def test_get_athlete_profile(session: Session, settings: Settings) -> None:
    user_id, repo = _create_user_and_credential(session)
    auth_service = DummyAuthService(settings)
    requester = FakeRequester([
        _make_response(200, json_body={"id": 4242, "firstname": "Rider"}),
    ])

    service = _build_service(settings, repo, auth_service, requester)

    profile = service.get_athlete_profile(user_id)
    assert profile["firstname"] == "Rider"


def test_get_athlete_stats(session: Session, settings: Settings) -> None:
    user_id, repo = _create_user_and_credential(session)
    auth_service = DummyAuthService(settings)
    requester = FakeRequester([
        _make_response(200, json_body={"recent_ride_totals": {"count": 5}}),
    ])

    service = _build_service(settings, repo, auth_service, requester)

    stats = service.get_athlete_stats(user_id)
    assert stats["recent_ride_totals"]["count"] == 5


def test_get_segment(session: Session, settings: Settings) -> None:
    user_id, repo = _create_user_and_credential(session)
    auth_service = DummyAuthService(settings)
    requester = FakeRequester([
        _make_response(200, json_body={"id": 123, "name": "Hill"}),
    ])

    service = _build_service(settings, repo, auth_service, requester)

    segment = service.get_segment(user_id, 123)
    assert segment["name"] == "Hill"


def test_list_routes(session: Session, settings: Settings) -> None:
    user_id, repo = _create_user_and_credential(session)
    auth_service = DummyAuthService(settings)
    requester = FakeRequester([
        _make_response(200, json_body=[{"id": 1, "name": "Route"}]),
    ])

    service = _build_service(settings, repo, auth_service, requester)

    routes = service.list_routes(user_id)
    assert routes[0]["name"] == "Route"


def test_get_route_streams(session: Session, settings: Settings) -> None:
    user_id, repo = _create_user_and_credential(session)
    auth_service = DummyAuthService(settings)
    requester = FakeRequester([
        _make_response(200, json_body={"latlng": {"type": "latlng", "data": []}}),
    ])

    service = _build_service(settings, repo, auth_service, requester)

    streams = service.get_route_streams(user_id, 99, keys=["latlng"])
    assert "latlng" in streams
