"""Strava-specific helpers for OAuth and API interactions."""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode

import httpx

from app.core.config import Settings
from app.schemas.strava import StravaTokenExchangeResponse


class StravaAuthError(Exception):
    """Raised when Strava authentication related flow fails."""


@dataclass(slots=True)
class StravaAuthService:
    settings: Settings

    def generate_state(self) -> str:
        """Create a 32-character hex state token for CSRF mitigation."""
        return secrets.token_hex(16)

    def build_authorize_url(self, state: str) -> str:
        query = {
            "client_id": self.settings.strava_client_id,
            "redirect_uri": str(self.settings.strava_redirect_uri),
            "response_type": "code",
            "scope": self.settings.strava_scope,
            "approval_prompt": "auto",
            "state": state,
        }
        return f"{self.settings.strava_authorize_base}?{urlencode(query)}"

    def exchange_code_for_tokens(self, code: str) -> StravaTokenExchangeResponse:
        payload = {
            "client_id": self.settings.strava_client_id,
            "client_secret": self.settings.strava_client_secret,
            "code": code,
            "grant_type": "authorization_code",
        }

        try:
            response = httpx.post(
                str(self.settings.strava_token_url),
                data=payload,
                timeout=10.0,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:  # pragma: no cover - wrapped below
            raise StravaAuthError("Error contacting Strava token endpoint") from exc

        data = response.json()
        try:
            exchange = StravaTokenExchangeResponse(
                access_token=data["access_token"],
                refresh_token=data["refresh_token"],
                token_type=data.get("token_type", "Bearer"),
                scope=data.get("scope", self.settings.strava_scope),
                expires_at=_resolve_expires_at(data),
                athlete_id=_extract_athlete_id(data),
            )
        except (KeyError, TypeError, ValueError) as exc:  # pragma: no cover - defensive
            raise StravaAuthError("Strava token payload malformed") from exc

        return exchange

    def refresh_access_token(self, refresh_token: str, *, athlete_id: int | None = None) -> StravaTokenExchangeResponse:
        payload = {
            "client_id": self.settings.strava_client_id,
            "client_secret": self.settings.strava_client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        }

        try:
            response = httpx.post(
                str(self.settings.strava_token_url),
                data=payload,
                timeout=10.0,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:  # pragma: no cover - wrapped below
            raise StravaAuthError("Error refreshing Strava access token") from exc

        data = response.json()
        try:
            exchange = StravaTokenExchangeResponse(
                access_token=data["access_token"],
                refresh_token=data.get("refresh_token", refresh_token),
                token_type=data.get("token_type", "Bearer"),
                scope=data.get("scope", self.settings.strava_scope),
                expires_at=_resolve_expires_at(data),
                athlete_id=_extract_athlete_id(data, fallback=athlete_id),
            )
        except (KeyError, TypeError, ValueError) as exc:  # pragma: no cover - defensive
            raise StravaAuthError("Strava refresh payload malformed") from exc

        return exchange


def _resolve_expires_at(data: dict[str, Any]) -> datetime:
    expires_at = data.get("expires_at")
    if isinstance(expires_at, (int, float)):
        return datetime.fromtimestamp(expires_at, tz=timezone.utc)
    if isinstance(expires_at, datetime):
        return expires_at
    raise ValueError("expires_at missing or invalid")


def _extract_athlete_id(data: dict[str, Any], fallback: int | None = None) -> int:
    athlete = data.get("athlete")
    if isinstance(athlete, dict) and isinstance(athlete.get("id"), int):
        return athlete["id"]
    if fallback is not None:
        return fallback
    raise ValueError("Athlete id missing")
