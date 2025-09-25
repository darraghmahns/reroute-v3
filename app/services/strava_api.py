from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
import time

import httpx

from app.core.config import Settings
from app.repositories.strava import StravaCredentialRepository
from app.schemas.strava import StravaTokenExchangeResponse
from app.services.strava import StravaAuthService


class StravaAPIError(Exception):
    def __init__(self, message: str, status_code: int = 502) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


@dataclass
class StravaActivityService:
    settings: Settings
    credential_repo: StravaCredentialRepository
    auth_service: StravaAuthService
    request_func: Callable[..., httpx.Response] | None = None
    sleep: Callable[[float], None] = time.sleep

    API_BASE = "https://www.strava.com/api/v3"

    def __post_init__(self) -> None:
        if self.request_func is None:
            self.request_func = self._default_request

    def list_activities(self, user_id: int, *, page: int = 1, per_page: int = 30) -> list[dict[str, Any]]:
        credential = self.credential_repo.get_by_user_id(user_id)
        if credential is None:
            raise StravaAPIError("Strava account not linked", status_code=404)

        credential = self._ensure_valid_token(credential)

        params = {"page": page, "per_page": per_page}
        url = f"{self.API_BASE}/athlete/activities"

        def _make_request(access_token: str) -> httpx.Response:
            headers = {"Authorization": f"Bearer {access_token}"}
            assert self.request_func is not None
            return self.request_func(
                "GET",
                url,
                headers=headers,
                params=params,
                timeout=10.0,
            )

        response = _make_request(credential.access_token)
        if response.status_code == 200:
            return response.json()

        if response.status_code == 401:
            credential = self._refresh_tokens(credential, credential.refresh_token, credential.user_id)
            response = _make_request(credential.access_token)
            if response.status_code == 200:
                return response.json()

        if response.status_code == 429:
            retry_after = float(response.headers.get("Retry-After", "1"))
            self.sleep(retry_after)
            response = _make_request(credential.access_token)
            if response.status_code == 200:
                return response.json()
            if response.status_code == 429:
                raise StravaAPIError("Strava rate limited", status_code=429)

        raise StravaAPIError(
            f"Strava API error {response.status_code}",
            status_code=502,
        )

    def get_athlete_profile(self, user_id: int) -> dict[str, Any]:
        return self._get_json(user_id, "/athlete", not_found_message="Strava athlete not found")

    def get_athlete_stats(self, user_id: int) -> dict[str, Any]:
        credential = self.credential_repo.get_by_user_id(user_id)
        if credential is None:
            raise StravaAPIError("Strava account not linked", status_code=404)
        credential = self._ensure_valid_token(credential)
        athlete_id = getattr(credential, "athlete_id", None)
        if athlete_id is None:
            raise StravaAPIError("Strava athlete id missing", status_code=502)
        return self._get_json(
            user_id,
            f"/athletes/{athlete_id}/stats",
            credential=credential,
            not_found_message="Strava athlete stats not found",
        )

    def get_activity(
        self,
        user_id: int,
        activity_id: int,
        *,
        include_all_efforts: bool = False,
    ) -> dict[str, Any]:
        credential = self.credential_repo.get_by_user_id(user_id)
        if credential is None:
            raise StravaAPIError("Strava account not linked", status_code=404)

        credential = self._ensure_valid_token(credential)

        url = f"{self.API_BASE}/activities/{activity_id}"
        params = {"include_all_efforts": str(include_all_efforts).lower()}

        def _make_request(access_token: str) -> httpx.Response:
            headers = {"Authorization": f"Bearer {access_token}"}
            assert self.request_func is not None
            return self.request_func(
                "GET",
                url,
                headers=headers,
                params=params,
                timeout=10.0,
            )

        response = _make_request(credential.access_token)
        if response.status_code == 200:
            return response.json()

        if response.status_code == 401:
            credential = self._refresh_tokens(credential, credential.refresh_token, credential.user_id)
            response = _make_request(credential.access_token)
            if response.status_code == 200:
                return response.json()

        if response.status_code == 429:
            retry_after = float(response.headers.get("Retry-After", "1"))
            self.sleep(retry_after)
            response = _make_request(credential.access_token)
            if response.status_code == 200:
                return response.json()
            if response.status_code == 429:
                raise StravaAPIError("Strava rate limited", status_code=429)

        if response.status_code == 404:
            raise StravaAPIError("Strava activity not found", status_code=404)

        raise StravaAPIError(
            f"Strava API error {response.status_code}",
            status_code=502,
        )

    def get_activity_streams(
        self,
        user_id: int,
        activity_id: int,
        *,
        keys: list[str],
        key_by_type: bool = True,
    ) -> Any:
        credential = self.credential_repo.get_by_user_id(user_id)
        if credential is None:
            raise StravaAPIError("Strava account not linked", status_code=404)

        credential = self._ensure_valid_token(credential)

        url = f"{self.API_BASE}/activities/{activity_id}/streams"
        params = {
            "keys": ",".join(keys),
            "key_by_type": str(key_by_type).lower(),
        }

        def _make_request(access_token: str) -> httpx.Response:
            headers = {"Authorization": f"Bearer {access_token}"}
            assert self.request_func is not None
            return self.request_func(
                "GET",
                url,
                headers=headers,
                params=params,
                timeout=10.0,
            )

        response = _make_request(credential.access_token)
        if response.status_code == 200:
            return response.json()

        if response.status_code == 401:
            credential = self._refresh_tokens(credential, credential.refresh_token, credential.user_id)
            response = _make_request(credential.access_token)
            if response.status_code == 200:
                return response.json()

        if response.status_code == 429:
            retry_after = float(response.headers.get("Retry-After", "1"))
            self.sleep(retry_after)
            response = _make_request(credential.access_token)
            if response.status_code == 200:
                return response.json()
            if response.status_code == 429:
                raise StravaAPIError("Strava rate limited", status_code=429)

        if response.status_code == 404:
            raise StravaAPIError("Strava activity not found", status_code=404)

        raise StravaAPIError(
            f"Strava API error {response.status_code}",
            status_code=502,
        )

    def get_segment(self, user_id: int, segment_id: int) -> dict[str, Any]:
        return self._get_json(
            user_id,
            f"/segments/{segment_id}",
            not_found_message="Strava segment not found",
        )

    def list_starred_segments(self, user_id: int, *, page: int = 1, per_page: int = 30) -> list[dict[str, Any]]:
        result = self._get_json(
            user_id,
            "/segments/starred",
            params={"page": page, "per_page": per_page},
        )
        if isinstance(result, list):
            return result
        return []

    def explore_segments(
        self,
        user_id: int,
        *,
        bounds: str,
        activity_type: str | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"bounds": bounds}
        if activity_type:
            params["activity_type"] = activity_type
        result = self._get_json(
            user_id,
            "/segments/explore",
            params=params,
            not_found_message="No segments found",
        )
        if isinstance(result, dict) and "segments" in result:
            return result["segments"]
        if isinstance(result, list):
            return result
        return []

    def list_routes(self, user_id: int) -> list[dict[str, Any]]:
        credential = self.credential_repo.get_by_user_id(user_id)
        if credential is None:
            raise StravaAPIError("Strava account not linked", status_code=404)
        credential = self._ensure_valid_token(credential)
        athlete_id = getattr(credential, "athlete_id", None)
        if athlete_id is None:
            raise StravaAPIError("Strava athlete id missing", status_code=502)
        result = self._get_json(
            user_id,
            f"/athletes/{athlete_id}/routes",
            credential=credential,
            not_found_message="No routes found",
        )
        if isinstance(result, list):
            return result
        return []

    def get_route(self, user_id: int, route_id: int) -> dict[str, Any]:
        return self._get_json(
            user_id,
            f"/routes/{route_id}",
            not_found_message="Strava route not found",
        )

    def get_route_streams(
        self,
        user_id: int,
        route_id: int,
        *,
        keys: list[str] | None = None,
    ) -> Any:
        params = {"keys": ",".join(keys)} if keys else {}
        return self._get_json(
            user_id,
            f"/routes/{route_id}/streams",
            params=params,
            not_found_message="Strava route not found",
        )

    def _ensure_valid_token(self, credential):
        now = datetime.now(timezone.utc)
        if credential.expires_at <= now + timedelta(minutes=1):
            credential = self._refresh_tokens(credential, credential.refresh_token, credential.user_id)
        return credential

    def _refresh_tokens(self, credential, refresh_token: str, user_id: int):
        exchange = self.auth_service.refresh_access_token(
            refresh_token,
            athlete_id=getattr(credential, "athlete_id", None),
        )
        return self._store_exchange(user_id, exchange)

    def _store_exchange(self, user_id: int, exchange: StravaTokenExchangeResponse):
        return self.credential_repo.upsert_from_token_exchange(
            user_id=user_id,
            athlete_id=exchange.athlete_id,
            access_token=exchange.access_token,
            refresh_token=exchange.refresh_token,
            token_type=exchange.token_type,
            scope=exchange.scope,
            expires_at=exchange.expires_at,
        )

    @staticmethod
    def _default_request(
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> httpx.Response:
        return httpx.request(method, url, headers=headers, params=params, timeout=timeout)

    def _get_json(
        self,
        user_id: int,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        credential=None,
        not_found_message: str = "Strava resource not found",
    ) -> Any:
        params = params or {}
        if credential is None:
            credential = self.credential_repo.get_by_user_id(user_id)
            if credential is None:
                raise StravaAPIError("Strava account not linked", status_code=404)
            credential = self._ensure_valid_token(credential)
        else:
            credential = self._ensure_valid_token(credential)

        url = f"{self.API_BASE}{path}"

        def _make_request(access_token: str) -> httpx.Response:
            headers = {"Authorization": f"Bearer {access_token}"}
            assert self.request_func is not None
            return self.request_func(
                "GET",
                url,
                headers=headers,
                params=params,
                timeout=10.0,
            )

        response = _make_request(credential.access_token)
        if response.status_code == 200:
            return response.json()

        if response.status_code == 401:
            credential = self._refresh_tokens(credential, credential.refresh_token, credential.user_id)
            response = _make_request(credential.access_token)
            if response.status_code == 200:
                return response.json()

        if response.status_code == 429:
            retry_after = float(response.headers.get("Retry-After", "1"))
            self.sleep(retry_after)
            response = _make_request(credential.access_token)
            if response.status_code == 200:
                return response.json()
            if response.status_code == 429:
                raise StravaAPIError("Strava rate limited", status_code=429)

        if response.status_code == 404:
            raise StravaAPIError(not_found_message, status_code=404)

        raise StravaAPIError(
            f"Strava API error {response.status_code}",
            status_code=502,
        )
