from __future__ import annotations

from sqlalchemy.orm import Session

from app.ai.openai_client import OpenAIClient
from app.ai.plan_agent import PlanAgent
from app.core.config import Settings
from app.repositories.ai import AIExecutionLogRepository
from app.repositories.strava import StravaCredentialRepository
from app.repositories.training import TrainingPlanRepository
from app.repositories.user import UserRepository
from app.services.plan_service import PlanService
from app.services.strava import StravaAuthService
from app.services.strava_api import StravaActivityService


def create_plan_service(
    session: Session,
    settings: Settings,
    *,
    strava_service: StravaActivityService | None = None,
    openai_client: OpenAIClient | None = None,
    ai_log_repository: AIExecutionLogRepository | None = None,
) -> PlanService:
    plan_repo = TrainingPlanRepository(session)
    user_repo = UserRepository(session)

    if strava_service is None:
        credential_repo = StravaCredentialRepository(session)
        auth_service = StravaAuthService(settings)
        strava_service = StravaActivityService(
            settings=settings,
            credential_repo=credential_repo,
            auth_service=auth_service,
        )

    if openai_client is None and settings.openai_api_key:
        try:
            openai_client = OpenAIClient(settings)
        except ValueError:
            openai_client = None

    agent = PlanAgent(
        model_name=settings.openai_model,
        temperature=settings.openai_temperature,
        max_output_tokens=settings.openai_max_output_tokens,
        openai_client=openai_client,
    )

    ai_logs = ai_log_repository or AIExecutionLogRepository(session)

    return PlanService(
        session,
        plan_repo,
        user_repo,
        agent,
        strava_service=strava_service,
        ai_log_repository=ai_logs,
    )
