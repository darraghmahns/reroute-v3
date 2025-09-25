from __future__ import annotations

from typing import List

from pydantic import BaseModel, Field


class PowerSummary(BaseModel):
    average: float | None = None
    normalized: float | None = None
    intensity_factor: float | None = None
    tss: float | None = None


class HeartRateSummary(BaseModel):
    average: float | None = None
    max: float | None = None
    time_in_zones: List[float] = Field(default_factory=list)


class StreamSummary(BaseModel):
    duration_seconds: int | None = None
    moving_seconds: int | None = None
    distance_km: float | None = None
    average_speed_kph: float | None = None
    power: PowerSummary | None = None
    heart_rate: HeartRateSummary | None = None
    cadence_avg: float | None = None
