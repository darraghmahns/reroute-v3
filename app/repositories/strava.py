from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.strava import StravaCredential


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class StravaCredentialRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_user_id(self, user_id: int) -> StravaCredential | None:
        statement = select(StravaCredential).where(StravaCredential.user_id == user_id)
        credential = self._session.scalar(statement)
        if credential and credential.expires_at is not None:
            credential.expires_at = _ensure_utc(credential.expires_at)
        return credential

    def get_by_athlete_id(self, athlete_id: int) -> StravaCredential | None:
        statement = select(StravaCredential).where(StravaCredential.athlete_id == athlete_id)
        credential = self._session.scalar(statement)
        if credential and credential.expires_at is not None:
            credential.expires_at = _ensure_utc(credential.expires_at)
        return credential

    def upsert_from_token_exchange(
        self,
        *,
        user_id: int,
        athlete_id: int,
        access_token: str,
        refresh_token: str,
        token_type: str,
        scope: list[str] | str,
        expires_at: datetime,
    ) -> StravaCredential:
        scope_value = ",".join(scope) if isinstance(scope, list) else scope

        credential = self.get_by_user_id(user_id)
        if credential:
            credential.athlete_id = athlete_id
            credential.access_token = access_token
            credential.refresh_token = refresh_token
            credential.token_type = token_type
            credential.scope = scope_value
            credential.expires_at = _ensure_utc(expires_at)
            self._session.add(credential)
            self._session.commit()
            self._session.refresh(credential)
            credential.expires_at = _ensure_utc(credential.expires_at)
            return credential

        credential = StravaCredential(
            user_id=user_id,
            athlete_id=athlete_id,
            access_token=access_token,
            refresh_token=refresh_token,
            token_type=token_type,
            scope=scope_value,
            expires_at=_ensure_utc(expires_at),
        )
        self._session.add(credential)
        self._session.commit()
        self._session.refresh(credential)
        credential.expires_at = _ensure_utc(credential.expires_at)
        return credential
