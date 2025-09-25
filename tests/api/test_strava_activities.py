from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from jose import jwt
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.dependencies.db import get_db_session
from app.api.dependencies.strava import get_strava_activity_service
from app.api.dependencies.auth import get_current_user
from app.models import strava as strava_models  # noqa: F401 ensure registration
from app.models import user as user_models  # noqa: F401 ensure registration
from app.models.base import Base
from app.repositories.user import UserRepository
from app.repositories.strava import StravaCredentialRepository
from app.schemas.strava import StravaActivitySummary
from app.services.strava_api import StravaAPIError, StravaActivityService


@pytest.fixture()
def make_token() -> callable:
    secret = "test-secret"

    def _build(sub: str, email: str = "rider@example.com", name: str = "Rider Example") -> str:
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

    return _build


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


class FakeActivityService(StravaActivityService):
    def __init__(
        self,
        activities,
        error: StravaAPIError | None = None,
        details: dict[int, dict] | None = None,
        streams: dict[int, Any] | None = None,
        athlete_profile: dict[str, Any] | None = None,
        athlete_stats: dict[str, Any] | None = None,
        segments: dict[str, Any] | None = None,
        routes: dict[str, Any] | None = None,
        route_streams: dict[int, Any] | None = None,
    ):
        self._activities = activities
        self._error = error
        self._details = details or {}
        self._streams = streams or {}
        self._athlete_profile = athlete_profile or {"id": 4242}
        self._athlete_stats = athlete_stats or {"recent_ride_totals": {}}
        self._segments = segments or {"starred": [], "explore": []}
        self._routes = routes or {"list": [], "detail": {}}
        self._route_streams = route_streams or {}

    def list_activities(self, user_id: int, *, page: int = 1, per_page: int = 30):  # type: ignore[override]
        if self._error:
            raise self._error
        return self._activities

    def get_activity(self, user_id: int, activity_id: int, *, include_all_efforts: bool = False):  # type: ignore[override]
        if self._error:
            raise self._error
        if activity_id not in self._details:
            raise StravaAPIError("Activity not found", status_code=404)
        return self._details[activity_id]

    def get_activity_streams(self, user_id: int, activity_id: int, *, keys: list[str], key_by_type: bool = True):  # type: ignore[override]
        if self._error:
            raise self._error
        if activity_id not in self._streams:
            raise StravaAPIError("Activity not found", status_code=404)
        return self._streams[activity_id]

    def get_athlete_profile(self, user_id: int):  # type: ignore[override]
        if self._error:
            raise self._error
        return self._athlete_profile

    def get_athlete_stats(self, user_id: int):  # type: ignore[override]
        if self._error:
            raise self._error
        return self._athlete_stats

    def list_starred_segments(self, user_id: int, *, page: int = 1, per_page: int = 30):  # type: ignore[override]
        if self._error:
            raise self._error
        return self._segments["starred"]

    def get_segment(self, user_id: int, segment_id: int):  # type: ignore[override]
        if self._error:
            raise self._error
        if "details" in self._segments and segment_id in self._segments["details"]:
            return self._segments["details"][segment_id]
        raise StravaAPIError("Segment not found", status_code=404)

    def explore_segments(self, user_id: int, *, bounds: str, activity_type: str | None = None):  # type: ignore[override]
        if self._error:
            raise self._error
        return self._segments.get("explore", [])

    def list_routes(self, user_id: int):  # type: ignore[override]
        if self._error:
            raise self._error
        return self._routes.get("list", [])

    def get_route(self, user_id: int, route_id: int):  # type: ignore[override]
        if self._error:
            raise self._error
        detail = self._routes.get("detail", {})
        if route_id in detail:
            return detail[route_id]
        raise StravaAPIError("Route not found", status_code=404)

    def get_route_streams(self, user_id: int, route_id: int, *, keys: list[str] | None = None):  # type: ignore[override]
        if self._error:
            raise self._error
        if route_id not in self._route_streams:
            raise StravaAPIError("Route not found", status_code=404)
        return self._route_streams[route_id]


@pytest.fixture()
def override_activity_service():
    from app.main import app as fastapi_app

    services = {}

    def _override(service):
        services["instance"] = service
        fastapi_app.dependency_overrides[get_strava_activity_service] = lambda: service

    yield _override

    fastapi_app.dependency_overrides.pop(get_strava_activity_service, None)


@pytest.fixture()
def auth_headers(make_token):
    token = make_token("auth0|user1")
    return {"Authorization": f"Bearer {token}"}


def _seed_user_with_strava(session_factory, *, include_credential: bool = True) -> None:
    SessionLocal: sessionmaker = session_factory  # type: ignore[assignment]
    with SessionLocal() as session:
        user_repo = UserRepository(session)
        user = user_repo.create_or_update_from_auth0(
            sub="auth0|user1",
            email="rider@example.com",
            name="Rider Example",
        )
        if include_credential:
            repo = StravaCredentialRepository(session)
            repo.upsert_from_token_exchange(
                user_id=user.id,
                athlete_id=4242,
                access_token="access",
                refresh_token="refresh",
                token_type="Bearer",
                scope=["read"],
                expires_at=datetime.now(tz=timezone.utc) + timedelta(hours=1),
            )


def test_activities_returns_data(client, db_override, override_activity_service, auth_headers):
    _seed_user_with_strava(db_override)
    activities = [
        {"id": 1, "name": "Ride"},
        {"id": 2, "name": "Commute"},
    ]
    override_activity_service(FakeActivityService(activities))

    response = client.get(
        "/v1/integrations/strava/activities",
        headers=auth_headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 2
    assert body[0]["id"] == 1


def test_activities_requires_strava_link(client, db_override, override_activity_service, auth_headers):
    _seed_user_with_strava(db_override, include_credential=False)
    override_activity_service(
        FakeActivityService(
            activities=[],
            error=StravaAPIError("not linked", status_code=404),
        )
    )

    response = client.get(
        "/v1/integrations/strava/activities",
        headers=auth_headers,
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Strava account not linked"


def test_activity_detail_returns_data(client, db_override, override_activity_service, auth_headers):
    _seed_user_with_strava(db_override)
    override_activity_service(
        FakeActivityService(
            activities=[],
            details={1: {"id": 1, "name": "Ride", "distance": 1000.0}},
        )
    )

    response = client.get(
        "/v1/integrations/strava/activities/1",
        headers=auth_headers,
        params={"include_all_efforts": True},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == 1


def test_activity_detail_requires_link(client, db_override, override_activity_service, auth_headers):
    _seed_user_with_strava(db_override, include_credential=False)
    override_activity_service(
        FakeActivityService(
            activities=[],
            error=StravaAPIError("not linked", status_code=404),
            details={},
        )
    )

    response = client.get(
        "/v1/integrations/strava/activities/1",
        headers=auth_headers,
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Strava account not linked"


def test_activity_detail_not_found(client, db_override, override_activity_service, auth_headers):
    _seed_user_with_strava(db_override)
    override_activity_service(
        FakeActivityService(
            activities=[],
            details={},
            streams={}
        )
    )

    response = client.get(
        "/v1/integrations/strava/activities/999",
        headers=auth_headers,
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Strava activity not found"


def test_activity_streams_returns_data(client, db_override, override_activity_service, auth_headers):
    _seed_user_with_strava(db_override)
    override_activity_service(
        FakeActivityService(
            activities=[],
            details={},
            streams={1: {"latlng": {"type": "latlng", "data": []}}},
        )
    )

    response = client.get(
        "/v1/integrations/strava/activities/1/streams",
        headers=auth_headers,
        params={"keys": "latlng,time", "key_by_type": True},
    )

    assert response.status_code == 200
    body = response.json()
    assert "latlng" in body


def test_activity_streams_requires_link(client, db_override, override_activity_service, auth_headers):
    _seed_user_with_strava(db_override, include_credential=False)
    override_activity_service(
        FakeActivityService(
            activities=[],
            error=StravaAPIError("not linked", status_code=404),
            details={},
            streams={},
        )
    )

    response = client.get(
        "/v1/integrations/strava/activities/1/streams",
        headers=auth_headers,
        params={"keys": "watts"},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Strava account not linked"

def test_athlete_profile_endpoint(client, db_override, override_activity_service, auth_headers):
    _seed_user_with_strava(db_override)
    override_activity_service(
        FakeActivityService(
            activities=[],
            athlete_profile={"id": 4242, "firstname": "Rider"},
        )
    )

    response = client.get(
        "/v1/integrations/strava/athlete/profile",
        headers=auth_headers,
    )
    assert response.status_code == 200
    assert response.json()["firstname"] == "Rider"


def test_athlete_stats_endpoint(client, db_override, override_activity_service, auth_headers):
    _seed_user_with_strava(db_override)
    override_activity_service(
        FakeActivityService(
            activities=[],
            athlete_stats={"recent_ride_totals": {"count": 3}},
        )
    )

    response = client.get(
        "/v1/integrations/strava/athlete/stats",
        headers=auth_headers,
    )
    assert response.status_code == 200
    assert response.json()["recent_ride_totals"]["count"] == 3


def test_segments_endpoints(client, db_override, override_activity_service, auth_headers):
    _seed_user_with_strava(db_override)
    override_activity_service(
        FakeActivityService(
            activities=[],
            segments={
                "starred": [{"id": 1, "name": "Hill"}],
                "explore": [{"id": 2, "name": "Climb"}],
                "details": {1: {"id": 1, "name": "Hill"}},
            },
        )
    )

    starred = client.get("/v1/integrations/strava/segments/starred", headers=auth_headers)
    assert starred.status_code == 200
    assert starred.json()[0]["name"] == "Hill"

    detail = client.get("/v1/integrations/strava/segments/1", headers=auth_headers)
    assert detail.status_code == 200
    assert detail.json()["name"] == "Hill"

    explore = client.get(
        "/v1/integrations/strava/segments/explore",
        headers=auth_headers,
        params={"bounds": "0,0,1,1"},
    )
    assert explore.status_code == 200, explore.json()
    assert len(explore.json()) == 1


def test_routes_endpoints(client, db_override, override_activity_service, auth_headers):
    _seed_user_with_strava(db_override)
    override_activity_service(
        FakeActivityService(
            activities=[],
            routes={
                "list": [{"id": 10, "name": "Loop"}],
                "detail": {10: {"id": 10, "name": "Loop"}},
            },
            route_streams={10: {"latlng": {"type": "latlng", "data": []}}},
        )
    )

    routes = client.get("/v1/integrations/strava/routes", headers=auth_headers)
    assert routes.status_code == 200
    assert routes.json()[0]["name"] == "Loop"

    detail = client.get("/v1/integrations/strava/routes/10", headers=auth_headers)
    assert detail.status_code == 200
    assert detail.json()["name"] == "Loop"

    streams = client.get(
        "/v1/integrations/strava/routes/10/streams",
        headers=auth_headers,
        params={"keys": "latlng"},
    )
    assert streams.status_code == 200
    assert "latlng" in streams.json()
