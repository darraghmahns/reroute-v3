from datetime import datetime, timezone
from typing import Any

from pydantic import AnyHttpUrl, BaseModel, Field, field_validator


class StravaAuthorizeResponse(BaseModel):
    authorize_url: AnyHttpUrl


class StravaTokenExchangeResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str
    scope: list[str]
    expires_at: datetime
    athlete_id: int

    @field_validator("expires_at", mode="before")
    @classmethod
    def _coerce_expires_at(cls, value: int | float | datetime) -> datetime:
        if isinstance(value, datetime):
            return value
        return datetime.fromtimestamp(value, tz=timezone.utc)

    @field_validator("scope", mode="before")
    @classmethod
    def _coerce_scope(cls, value: list[str] | str) -> list[str]:
        if isinstance(value, list):
            return value
        if isinstance(value, str):
            return [chunk for chunk in value.split(",") if chunk]
        raise TypeError("Invalid scope type")


class StravaActivitySummary(BaseModel):
    model_config = {
        "extra": "ignore",
    }

    id: int
    name: str | None = None
    distance: float | None = None
    moving_time: int | None = Field(default=None, alias="moving_time")
    elapsed_time: int | None = Field(default=None, alias="elapsed_time")
    type: str | None = None
    start_date: datetime | None = Field(default=None, alias="start_date")


class StravaActivityDetail(StravaActivitySummary):
    description: str | None = None
    trainer: int | None = None
    commute: bool | None = None
    average_speed: float | None = Field(default=None, alias="average_speed")
    max_speed: float | None = Field(default=None, alias="max_speed")
    total_elevation_gain: float | None = Field(default=None, alias="total_elevation_gain")


class StravaStream(BaseModel):
    type: str | None = None
    data: list[Any]
    series_type: str | None = Field(default=None, alias="series_type")
    original_size: int | None = Field(default=None, alias="original_size")
    resolution: str | None = None


class StravaAthleteProfile(BaseModel):
    id: int
    username: str | None = None
    firstname: str | None = None
    lastname: str | None = None
    city: str | None = None
    country: str | None = None
    sex: str | None = None
    summit: bool | None = Field(default=None, alias="premium")
    ftp: int | None = None
    weight: float | None = None
    profile: AnyHttpUrl | None = None


class StravaAthleteStats(BaseModel):
    biggest_ride_distance: float | None = None
    biggest_climb_elevation_gain: float | None = None
    recent_ride_totals: dict[str, Any] | None = None
    ytd_ride_totals: dict[str, Any] | None = None
    all_ride_totals: dict[str, Any] | None = None


class StravaSegmentSummary(BaseModel):
    id: int
    name: str | None = None
    distance: float | None = None
    average_grade: float | None = Field(default=None, alias="avg_grade")
    maximum_grade: float | None = None
    climb_category: int | None = None
    city: str | None = None
    state: str | None = None
    country: str | None = None
    elevation_high: float | None = None
    elevation_low: float | None = None


class StravaRouteSummary(BaseModel):
    id: int
    name: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    distance: float | None = None
    description: str | None = None
    type: int | None = None
    sub_type: int | None = Field(default=None, alias="sub_type")
    map: dict[str, Any] | None = None
    privacy: str | None = None


class StravaWebhookEvent(BaseModel):
    object_type: str
    object_id: int
    aspect_type: str
    owner_id: int
    updates: dict[str, Any] = Field(default_factory=dict)
    event_time: int | None = None
    subscription_id: int | None = None
