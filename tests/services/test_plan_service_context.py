from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.ai.plan_agent import AgentInvocationResult
from app.models import training as training_models  # noqa: F401 ensure metadata
from app.models import user as user_models  # noqa: F401 ensure metadata
from app.models.base import Base
from app.repositories.training import TrainingPlanRepository
from app.repositories.user import UserRepository
from app.schemas.plan import ActivitySummary, PlanAdjustmentRequest, PlanGenerationRequest, TrainingPlanSchema
from app.services.plan_service import PlanService


def _setup_session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return Session(engine)


class StubPlanAgent:
    def __init__(self) -> None:
        self.last_generation_context = None
        self.last_adjustment_context = None
        self.model_name = "stub-model"

    def generate_plan(self, context):  # type: ignore[override]
        self.last_generation_context = context
        plan = TrainingPlanSchema(name="Stub Plan", goal=context.preferences.get("goal"), blocks=[], workouts=[])
        prompt = "PLAN_GENERATION_CONTEXT:\n" + context.model_dump_json(indent=2)
        return AgentInvocationResult(
            plan=plan,
            prompt=prompt,
            messages_json=None,
            usage=None,
            model_name=self.model_name,
        )

    def adjust_plan(self, context):  # type: ignore[override]
        self.last_adjustment_context = context
        plan = context.plan
        prompt = "PLAN_ADJUSTMENT_CONTEXT:\n" + context.model_dump_json(indent=2)
        return AgentInvocationResult(
            plan=plan,
            prompt=prompt,
            messages_json=None,
            usage=None,
            model_name=self.model_name,
        )


class RecordingAIRepository:
    def __init__(self) -> None:
        self.records: list[dict] = []

    def record(
        self,
        *,
        user_id: int,
        plan_id: int | None,
        job_type: str,
        model_name: str | None,
        prompt: str,
        response: str | None,
        tokens_used: int | None,
        cost_usd: float | None,
    ) -> None:
        self.records.append(
            {
                "user_id": user_id,
                "plan_id": plan_id,
                "job_type": job_type,
                "model_name": model_name,
                "prompt": prompt,
                "response": response,
                "tokens_used": tokens_used,
                "cost_usd": cost_usd,
            }
        )


class FakeStravaService:
    def __init__(self) -> None:
        start = datetime.now(timezone.utc) - timedelta(days=1)
        self._activities = [
            {
                "id": 42,
                "sport_type": "Ride",
                "moving_time": 3600,
                "distance": 30000,
                "start_date": start.isoformat(),
                "description": "Endurance spin",
            }
        ]
        steps = [i * 60 for i in range(61)]
        self._streams = {
            "time": {"data": steps},
            "watts": {"data": [210.0 for _ in steps]},
            "heartrate": {"data": [142.0 for _ in steps]},
            "cadence": {"data": [88.0 for _ in steps]},
            "distance": {"data": [float(i) * 500 for i in range(61)]},
            "moving": {"data": [1 for _ in steps]},
        }
        self._profile = {
            "id": 1001,
            "firstname": "Test",
            "lastname": "Rider",
            "ftp": 260,
            "weight": 72.0,
        }
        self._stats = {
            "recent_ride_totals": {"count": 6, "moving_time": 21600},
            "ytd_ride_totals": {"count": 120},
            "all_ride_totals": {"count": 500},
        }

    def list_activities(self, user_id: int, *, page: int = 1, per_page: int = 30):  # noqa: D401
        return self._activities

    def get_activity_streams(
        self,
        user_id: int,
        activity_id: int,
        *,
        keys: list[str],
        key_by_type: bool = True,
    ):
        return self._streams

    def get_athlete_profile(self, user_id: int):
        return self._profile

    def get_athlete_stats(self, user_id: int):
        return self._stats


def test_generate_plan_includes_strava_context() -> None:
    session = _setup_session()
    plan_repo = TrainingPlanRepository(session)
    user_repo = UserRepository(session)

    user = user_repo.create_or_update_from_auth0(sub="auth0|ctx", email="ctx@example.com", name="Context Rider")
    user_repo.update_user(user, timezone="UTC")

    agent = StubPlanAgent()
    strava_service = FakeStravaService()
    logs = RecordingAIRepository()
    service = PlanService(
        session,
        plan_repo,
        user_repo,
        agent,
        strava_service=strava_service,
        ai_log_repository=logs,
    )

    request = PlanGenerationRequest(goal="Base Build", duration_weeks=6)
    plan = service.generate_plan_for_user(user.id, request)

    assert plan.goal == "Base Build"
    assert agent.last_generation_context is not None
    ctx = agent.last_generation_context
    assert ctx.recent_activities, "expected recent activities from Strava"
    assert ctx.recent_activities[0].streams is not None
    assert ctx.athlete_stats is not None
    assert ctx.empathy_cues, "expected empathy cues derived from activity data"

    assert logs.records, "expected agent execution to be logged"
    first_log = logs.records[0]
    assert first_log["job_type"] == "plan.generate"
    assert "PLAN_GENERATION_CONTEXT" in first_log["prompt"]

    session.close()


def test_adjust_plan_uses_latest_activity() -> None:
    session = _setup_session()
    plan_repo = TrainingPlanRepository(session)
    user_repo = UserRepository(session)

    user = user_repo.create_or_update_from_auth0(sub="auth0|adj", email="adj@example.com", name="Adjust Rider")
    user_repo.update_user(user, timezone="UTC")

    agent = StubPlanAgent()
    strava_service = FakeStravaService()
    logs = RecordingAIRepository()
    service = PlanService(
        session,
        plan_repo,
        user_repo,
        agent,
        strava_service=strava_service,
        ai_log_repository=logs,
    )

    generation_request = PlanGenerationRequest(goal="Race", duration_weeks=4)
    service.generate_plan_for_user(user.id, generation_request)

    adjust_request = PlanAdjustmentRequest(reason="Post activity auto adjust")
    updated_plan = service.adjust_plan(user.id, plan_id=1, request=adjust_request)

    assert updated_plan.goal == "Race"
    assert agent.last_adjustment_context is not None
    adj_ctx = agent.last_adjustment_context
    assert adj_ctx.latest_activity is not None
    assert adj_ctx.latest_activity.streams is not None
    assert adj_ctx.recent_activities, "expected recent activities on adjustment context"
    assert logs.records[-1]["job_type"] == "plan.adjust"

    session.close()
