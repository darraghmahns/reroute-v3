from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

try:  # pragma: no cover - optional dependency in tests
    import structlog
except ImportError:  # pragma: no cover
    import logging

    logger = logging.getLogger(__name__)
else:
    logger = structlog.get_logger(__name__)

from genai_prices import Usage as PriceUsage, calc_price
from sqlalchemy.orm import Session

from app.ai.plan_agent import AgentInvocationResult, PlanAgent
from app.repositories.ai import AIExecutionLogRepository
from app.repositories.training import TrainingPlanRepository
from app.repositories.user import UserRepository
from app.schemas.plan import (
    ActivitySummary,
    PlanAdjustmentContext,
    PlanAdjustmentRequest,
    PlanGenerationContext,
    PlanGenerationRequest,
    TrainingBlockSchema,
    TrainingPlanSchema,
    WorkoutSchema,
)
from app.schemas.strava import StravaAthleteProfile, StravaAthleteStats
from app.services.stream_metrics import summarize_streams
from app.services.strava_api import StravaAPIError, StravaActivityService
import app.schemas.plan as plan_schemas


RECENT_ACTIVITY_LIMIT = 5
DEFAULT_STREAM_KEYS = ["time", "distance", "heartrate", "cadence", "watts", "moving"]


class PlanService:
    def __init__(
        self,
        session: Session,
        plan_repository: TrainingPlanRepository,
        user_repository: UserRepository,
        plan_agent: PlanAgent,
        *,
        strava_service: StravaActivityService | None = None,
        ai_log_repository: AIExecutionLogRepository | None = None,
    ) -> None:
        self._session = session
        self._plan_repo = plan_repository
        self._user_repo = user_repository
        self._plan_agent = plan_agent
        self._strava_service = strava_service
        self._ai_log_repo = ai_log_repository

    def generate_plan_for_user(self, user_id: int, request: PlanGenerationRequest) -> TrainingPlanSchema:
        user = self._user_repo.get_by_id(user_id)
        if user is None:
            raise ValueError("User not found")

        context = self._build_generation_context(user_id, user, request)
        agent_result = self._plan_agent.generate_plan(context)
        plan_schema = agent_result.plan
        plan_schema.goal = plan_schema.goal or request.goal
        if request.start_date and not plan_schema.start_date:
            plan_schema.start_date = request.start_date

        created_plan = self._persist_plan_schema(user_id, plan_schema)
        created_plan_schema = self._plan_to_schema(created_plan)

        self._record_agent_run(
            user_id=user_id,
            plan_id=created_plan.id,
            job_type="plan.generate",
            agent_result=agent_result,
            response_plan=created_plan_schema,
        )

        return created_plan_schema

    def adjust_plan(
        self,
        user_id: int,
        plan_id: int,
        request: PlanAdjustmentRequest,
        activity: ActivitySummary | None = None,
    ) -> TrainingPlanSchema:
        plan = self._plan_repo.get_plan(plan_id)
        if plan is None:
            raise ValueError("Plan not found")
        if plan.user_id != user_id:
            raise PermissionError("Plan does not belong to user")

        user = self._user_repo.get_by_id(user_id)
        if user is None:
            raise ValueError("User not found")

        plan_schema = self._plan_to_schema(plan)
        context = self._build_adjustment_context(user_id, user, plan_schema, request, activity)
        agent_result = self._plan_agent.adjust_plan(context)
        adjusted_schema = agent_result.plan

        updated_plan = self._merge_plan(plan, adjusted_schema)
        updated_plan_schema = self._plan_to_schema(updated_plan)

        self._record_agent_run(
            user_id=user_id,
            plan_id=updated_plan.id,
            job_type="plan.adjust",
            agent_result=agent_result,
            response_plan=updated_plan_schema,
        )

        return updated_plan_schema

    def ensure_user(self, claims: dict) -> int:
        user = self._user_repo.create_or_update_from_auth0(
            sub=claims["sub"],
            email=claims.get("email"),
            name=claims.get("name"),
        )
        return user.id

    def list_plans(self, user_id: int) -> list[TrainingPlanSchema]:
        plans = self._plan_repo.list_plans_for_user(user_id)
        return [self._plan_to_schema(plan) for plan in plans]

    def get_plan(self, user_id: int, plan_id: int) -> TrainingPlanSchema | None:
        plan = self._plan_repo.get_plan(plan_id)
        if not plan:
            return None
        if plan.user_id != user_id:
            raise PermissionError("Plan does not belong to user")
        return self._plan_to_schema(plan)

    def update_plan(self, user_id: int, plan_id: int, **fields: object) -> TrainingPlanSchema:
        plan = self._plan_repo.get_plan(plan_id)
        if plan is None:
            raise ValueError("Plan not found")
        if plan.user_id != user_id:
            raise PermissionError("Plan does not belong to user")
        plan = self._plan_repo.update_plan(plan, **fields)
        return self._plan_to_schema(plan)

    def delete_plan(self, user_id: int, plan_id: int) -> None:
        plan = self._plan_repo.get_plan(plan_id)
        if plan is None:
            return
        if plan.user_id != user_id:
            raise PermissionError("Plan does not belong to user")
        self._plan_repo.delete_plan(plan)

    # ------------------------------------------------------------------
    # Context building helpers
    # ------------------------------------------------------------------
    def _build_generation_context(
        self,
        user_id: int,
        user,
        request: PlanGenerationRequest,
    ) -> PlanGenerationContext:
        athlete_profile = self._build_athlete_profile(
            user_id=user_id,
            user=user,
            goal=request.goal,
            existing_goals=[],
        )

        preferences = {
            key: value
            for key, value in {
                "goal": request.goal,
                "duration_weeks": request.duration_weeks,
            }.items()
            if value is not None
        }
        if request.start_date:
            preferences["start_date"] = request.start_date.isoformat()

        stats = self._fetch_athlete_stats(user_id)
        recent_activities = self._fetch_recent_activities(user_id, ftp=athlete_profile.ftp)
        empathy_cues = self._derive_empathy_cues(recent_activities, stats)

        return PlanGenerationContext(
            athlete=athlete_profile,
            recent_activities=recent_activities,
            preferences=preferences,
            athlete_stats=stats,
            empathy_cues=empathy_cues,
        )

    def _build_adjustment_context(
        self,
        user_id: int,
        user,
        plan_schema: TrainingPlanSchema,
        request: PlanAdjustmentRequest,
        activity: ActivitySummary | None,
    ) -> PlanAdjustmentContext:
        existing_goals = [plan_schema.goal] if plan_schema.goal else []
        athlete_profile = self._build_athlete_profile(
            user_id=user_id,
            user=user,
            goal=None,
            existing_goals=existing_goals,
        )
        stats = self._fetch_athlete_stats(user_id)
        recent_activities = self._fetch_recent_activities(user_id, ftp=athlete_profile.ftp)

        if activity is not None:
            activity = self._ensure_activity_streams(user_id, activity, athlete_profile.ftp)
            recent_activities = [activity] + [
                item for item in recent_activities if item.activity_id != activity.activity_id
            ]

        latest_activity = recent_activities[0] if recent_activities else None
        empathy_cues = self._derive_empathy_cues(recent_activities, stats)

        return PlanAdjustmentContext(
            plan=plan_schema,
            latest_activity=latest_activity,
            adjustment_reason=request.reason,
            athlete=athlete_profile,
            athlete_stats=stats,
            recent_activities=recent_activities,
            empathy_cues=empathy_cues,
        )

    def _build_athlete_profile(
        self,
        *,
        user_id: int,
        user,
        goal: str | None,
        existing_goals: list[str],
    ) -> plan_schemas.AthleteProfile:
        ftp = None
        weight_kg = None
        if self._strava_service is not None:
            try:
                profile_data = self._strava_service.get_athlete_profile(user_id)
                profile = StravaAthleteProfile.model_validate(profile_data)
                ftp = profile.ftp
                weight_kg = profile.weight
            except StravaAPIError:
                profile = None
            except Exception:  # pragma: no cover - defensive validation
                profile = None

        goals = [item for item in existing_goals if item]
        if goal and goal not in goals:
            goals.append(goal)

        return plan_schemas.AthleteProfile(
            ftp=ftp,
            max_heart_rate=None,
            weight_kg=weight_kg,
            primary_sport="cycling",
            availability_hours_per_week=None,
            goals=goals,
            upcoming_event_date=None,
            timezone=getattr(user, "timezone", None),
        )

    def _fetch_athlete_stats(self, user_id: int) -> StravaAthleteStats | None:
        if self._strava_service is None:
            return None
        try:
            stats_raw = self._strava_service.get_athlete_stats(user_id)
        except StravaAPIError:
            return None
        try:
            return StravaAthleteStats.model_validate(stats_raw)
        except Exception:  # pragma: no cover - defensive validation
            return None

    def _fetch_recent_activities(self, user_id: int, *, ftp: float | None) -> list[ActivitySummary]:
        if self._strava_service is None:
            return []
        try:
            activities = self._strava_service.list_activities(
                user_id=user_id,
                page=1,
                per_page=RECENT_ACTIVITY_LIMIT,
            )
        except StravaAPIError:
            return []

        summaries: list[ActivitySummary] = []
        for raw_activity in activities[:RECENT_ACTIVITY_LIMIT]:
            summary = self._summarize_activity(user_id, raw_activity, ftp)
            if summary:
                summaries.append(summary)
        return summaries

    def _summarize_activity(
        self,
        user_id: int,
        raw_activity: dict[str, Any],
        ftp: float | None,
    ) -> ActivitySummary | None:
        if self._strava_service is None:
            return None
        try:
            activity_id = int(raw_activity["id"])
        except (KeyError, TypeError, ValueError):
            return None

        sport_type = raw_activity.get("sport_type") or raw_activity.get("type") or "ride"
        moving_time = raw_activity.get("moving_time") or raw_activity.get("moving_time_seconds") or 0
        distance = raw_activity.get("distance")
        distance_km = distance / 1000.0 if isinstance(distance, (int, float)) else None
        description = raw_activity.get("description")
        start_date = self._parse_datetime(raw_activity.get("start_date"))

        streams_summary = None
        try:
            stream_payload = self._strava_service.get_activity_streams(
                user_id=user_id,
                activity_id=activity_id,
                keys=DEFAULT_STREAM_KEYS,
                key_by_type=True,
            )
            if isinstance(stream_payload, dict):
                streams_summary = summarize_streams(streams=stream_payload, ftp=ftp)
        except StravaAPIError:
            streams_summary = None

        tss_value = None
        if streams_summary and streams_summary.power and streams_summary.power.tss is not None:
            tss_value = streams_summary.power.tss

        return ActivitySummary(
            activity_id=activity_id,
            sport_type=sport_type,
            moving_time_seconds=int(moving_time or 0),
            distance_km=distance_km,
            tss=tss_value,
            description=description,
            start_date=start_date,
            streams=streams_summary,
        )

    def _ensure_activity_streams(
        self,
        user_id: int,
        activity: ActivitySummary,
        ftp: float | None,
    ) -> ActivitySummary:
        if activity.streams is not None or self._strava_service is None:
            return activity
        try:
            stream_payload = self._strava_service.get_activity_streams(
                user_id=user_id,
                activity_id=activity.activity_id,
                keys=DEFAULT_STREAM_KEYS,
                key_by_type=True,
            )
            if isinstance(stream_payload, dict):
                streams_summary = summarize_streams(streams=stream_payload, ftp=ftp)
                return activity.model_copy(update={"streams": streams_summary})
        except StravaAPIError:
            return activity
        return activity

    def _derive_empathy_cues(
        self,
        recent_activities: list[ActivitySummary],
        stats: StravaAthleteStats | None,
    ) -> list[str]:
        cues: list[str] = []
        if recent_activities:
            latest = recent_activities[0]
            start_date = latest.start_date
            if start_date:
                latest_start = self._as_utc(start_date)
                days_since = (datetime.now(timezone.utc) - latest_start).days
                if days_since >= 4:
                    cues.append(f"No ride logged for {days_since} days — ease them back gently.")

            if latest.streams and latest.streams.power:
                power = latest.streams.power
                if power.tss and power.tss > 120:
                    cues.append(f"Latest ride carried a heavy load (TSS {int(power.tss)}).")
                if power.intensity_factor and power.intensity_factor > 1.05:
                    cues.append("Recent session pushed above FTP — plan for additional recovery.")

            if latest.moving_time_seconds and latest.moving_time_seconds > 7200:
                cues.append("Athlete handled a long ride recently — maintain endurance focus.")

        if stats and stats.recent_ride_totals:
            ride_count = stats.recent_ride_totals.get("count")
            moving_time = stats.recent_ride_totals.get("moving_time")
            if ride_count:
                cues.append(f"Completed {ride_count} rides in the last 4 weeks.")
            if moving_time:
                hours = round((moving_time or 0) / 3600, 1)
                if hours:
                    cues.append(f"Logged approximately {hours} hours recently — maintain load consistency.")

        # limit to a few key cues for prompt brevity
        return cues[:4]

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------
    def _persist_plan_schema(self, user_id: int, plan_schema: TrainingPlanSchema):
        plan = self._plan_repo.create_plan(
            user_id=user_id,
            name=plan_schema.name,
            goal=plan_schema.goal,
            start_date=plan_schema.start_date,
            end_date=plan_schema.end_date,
        )
        for index, block_schema in enumerate(plan_schema.blocks):
            block = self._plan_repo.add_block(
                plan,
                name=block_schema.name,
                focus=block_schema.focus,
                order_index=index,
                start_date=block_schema.start_date,
                end_date=block_schema.end_date,
            )
            for workout_schema in block_schema.workouts:
                self._plan_repo.add_workout(
                    plan,
                    block=block,
                    scheduled_date=workout_schema.scheduled_date,
                    sport_type=workout_schema.sport_type,
                    name=workout_schema.name,
                    description=workout_schema.description,
                    duration_minutes=workout_schema.duration_minutes,
                    distance_km=workout_schema.distance_km,
                    target_intensity=workout_schema.target_intensity,
                    target_tss=workout_schema.target_tss,
                )
        for workout_schema in plan_schema.workouts:
            self._plan_repo.add_workout(
                plan,
                block=None,
                scheduled_date=workout_schema.scheduled_date,
                sport_type=workout_schema.sport_type,
                name=workout_schema.name,
                description=workout_schema.description,
                duration_minutes=workout_schema.duration_minutes,
                distance_km=workout_schema.distance_km,
                target_intensity=workout_schema.target_intensity,
                target_tss=workout_schema.target_tss,
            )
        return self._plan_repo.get_plan(plan.id)

    def _merge_plan(self, plan, plan_schema: TrainingPlanSchema):
        return self._plan_repo.update_plan(
            plan,
            name=plan_schema.name,
            goal=plan_schema.goal,
            start_date=plan_schema.start_date,
            end_date=plan_schema.end_date,
            status=plan_schema.status,
        )

    def _plan_to_schema(self, plan) -> TrainingPlanSchema:
        blocks = []
        for block in sorted(plan.blocks, key=lambda b: b.order_index):
            block_schema = TrainingBlockSchema(
                name=block.name,
                focus=block.focus,
                start_date=block.start_date,
                end_date=block.end_date,
                workouts=[
                    WorkoutSchema(
                        scheduled_date=workout.scheduled_date,
                        sport_type=workout.sport_type,
                        name=workout.name,
                        description=workout.description,
                        duration_minutes=workout.duration_minutes,
                        distance_km=workout.distance_km,
                        target_intensity=workout.target_intensity,
                        target_tss=workout.target_tss,
                    )
                    for workout in block.workouts
                ],
            )
            blocks.append(block_schema)

        workouts = [
            WorkoutSchema(
                scheduled_date=workout.scheduled_date,
                sport_type=workout.sport_type,
                name=workout.name,
                description=workout.description,
                duration_minutes=workout.duration_minutes,
                distance_km=workout.distance_km,
                target_intensity=workout.target_intensity,
                target_tss=workout.target_tss,
            )
            for workout in plan.workouts
        ]

        return TrainingPlanSchema(
            name=plan.name,
            goal=plan.goal,
            start_date=plan.start_date,
            end_date=plan.end_date,
            status=plan.status,
            blocks=blocks,
            workouts=workouts,
        )

    # ------------------------------------------------------------------
    # Logging & metrics helpers
    # ------------------------------------------------------------------
    def _record_agent_run(
        self,
        *,
        user_id: int,
        plan_id: int | None,
        job_type: str,
        agent_result: AgentInvocationResult,
        response_plan: TrainingPlanSchema,
    ) -> None:
        usage = agent_result.usage
        model_name = agent_result.model_name

        tokens_used = None
        cost_value: float | None = None

        if usage is not None:
            input_tokens = getattr(usage, "input_tokens", 0) or 0
            output_tokens = getattr(usage, "output_tokens", 0) or 0
            tokens_used = input_tokens + output_tokens

            if model_name:
                try:
                    price_usage = PriceUsage(
                        input_tokens=input_tokens or None,
                        output_tokens=output_tokens or None,
                        cache_write_tokens=getattr(usage, "cache_write_tokens", 0) or None,
                        cache_read_tokens=getattr(usage, "cache_read_tokens", 0) or None,
                    )
                    price_details = calc_price(price_usage, model_name)
                    if getattr(price_details, "total_price", None) is not None:
                        cost_value = float(price_details.total_price)  # type: ignore[arg-type]
                except Exception:  # pragma: no cover - price catalog may not have model entry
                    cost_value = None

        logger.info(
            "plan_agent_run",
            job_type=job_type,
            user_id=user_id,
            plan_id=plan_id,
            model=model_name,
            tokens_used=tokens_used,
            cost_usd=cost_value,
            fallback=agent_result.fallback_used,
            error=agent_result.error,
        )

        if self._ai_log_repo is None:
            return

        prompt_payload = agent_result.prompt
        response_payload = response_plan.model_dump_json(by_alias=True, indent=2)

        self._ai_log_repo.record(
            user_id=user_id,
            plan_id=plan_id,
            job_type=job_type,
            model_name=model_name,
            prompt=prompt_payload,
            response=response_payload,
            tokens_used=tokens_used,
            cost_usd=cost_value,
        )

    # ------------------------------------------------------------------
    # Utility helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _parse_datetime(value: Any) -> datetime | None:
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            normalized = value.replace("Z", "+00:00")
            try:
                return datetime.fromisoformat(normalized)
            except ValueError:
                return None
        return None

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
