from __future__ import annotations

from datetime import date, datetime
from typing import List

from pydantic import BaseModel, Field

from app.schemas.metrics import StreamSummary
from app.schemas.strava import StravaAthleteStats


class AthleteProfile(BaseModel):
    ftp: float | None = None
    max_heart_rate: int | None = None
    weight_kg: float | None = None
    primary_sport: str | None = None
    availability_hours_per_week: float | None = None
    goals: List[str] = Field(default_factory=list)
    upcoming_event_date: date | None = None
    timezone: str | None = None


class ActivitySummary(BaseModel):
    activity_id: int
    sport_type: str
    moving_time_seconds: int
    distance_km: float | None = None
    tss: float | None = None
    description: str | None = None
    start_date: datetime | None = None
    streams: StreamSummary | None = None


class WorkoutSchema(BaseModel):
    scheduled_date: date | None = None
    sport_type: str | None = None
    name: str | None = None
    description: str | None = None
    duration_minutes: int | None = None
    distance_km: float | None = None
    target_intensity: str | None = None
    target_tss: int | None = None


class TrainingBlockSchema(BaseModel):
    name: str | None = None
    focus: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    workouts: List[WorkoutSchema] = Field(default_factory=list)


class TrainingPlanSchema(BaseModel):
    name: str | None = None
    goal: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    status: str = "draft"
    blocks: List[TrainingBlockSchema] = Field(default_factory=list)
    workouts: List[WorkoutSchema] = Field(default_factory=list)


class PlanGenerationContext(BaseModel):
    athlete: AthleteProfile
    recent_activities: List[ActivitySummary] = Field(default_factory=list)
    preferences: dict[str, str | float | int | bool] = Field(default_factory=dict)
    athlete_stats: StravaAthleteStats | None = None
    empathy_cues: List[str] = Field(default_factory=list)


class PlanAdjustmentContext(BaseModel):
    plan: TrainingPlanSchema
    latest_activity: ActivitySummary | None = None
    adjustment_reason: str | None = None
    athlete: AthleteProfile | None = None
    athlete_stats: StravaAthleteStats | None = None
    recent_activities: List[ActivitySummary] = Field(default_factory=list)
    empathy_cues: List[str] = Field(default_factory=list)


class PlanGenerationRequest(BaseModel):
    goal: str
    duration_weeks: int = 8
    start_date: date | None = None


class PlanAdjustmentRequest(BaseModel):
    reason: str
