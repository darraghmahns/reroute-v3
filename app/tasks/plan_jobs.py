from __future__ import annotations

from typing import Any

from app.core.config import get_settings
from app.db.session import session_scope
from app.schemas.plan import ActivitySummary, PlanAdjustmentRequest, PlanGenerationRequest
from app.services.plan_factory import create_plan_service


def generate_plan_job(user_id: int, request_data: dict[str, Any]) -> dict[str, Any]:
    settings = get_settings()
    request = PlanGenerationRequest.model_validate(request_data)

    with session_scope() as session:
        service = create_plan_service(session, settings)
        plan_schema = service.generate_plan_for_user(user_id, request)
        return plan_schema.model_dump(mode="json")


def adjust_plan_job(
    user_id: int,
    plan_id: int,
    request_data: dict[str, Any],
    activity_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    settings = get_settings()
    request = PlanAdjustmentRequest.model_validate(request_data)
    activity = ActivitySummary.model_validate(activity_data) if activity_data else None

    with session_scope() as session:
        service = create_plan_service(session, settings)
        plan_schema = service.adjust_plan(user_id, plan_id, request, activity)
        return plan_schema.model_dump(mode="json")
