from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.api.dependencies.auth import get_current_user
from app.api.dependencies.plan import get_plan_service
from app.api.dependencies.tasks import get_plan_task_dispatcher
from app.schemas.plan import (
    PlanAdjustmentRequest,
    PlanGenerationRequest,
    TrainingPlanSchema,
)
from app.services.plan_service import PlanService
from app.services.task_dispatcher import PlanTaskDispatcher

router = APIRouter(prefix="/v1/plans", tags=["plans"])


@router.get("/", response_model=list[TrainingPlanSchema])
def list_plans(
    claims: dict = Depends(get_current_user),
    service: PlanService = Depends(get_plan_service),
) -> list[TrainingPlanSchema]:
    user_id = service.ensure_user(claims)
    return service.list_plans(user_id)


@router.post("/generate", response_model=TrainingPlanSchema, status_code=status.HTTP_201_CREATED)
def generate_plan(
    request: PlanGenerationRequest,
    claims: dict = Depends(get_current_user),
    service: PlanService = Depends(get_plan_service),
    dispatcher: PlanTaskDispatcher = Depends(get_plan_task_dispatcher),
) -> TrainingPlanSchema:
    user_id = service.ensure_user(claims)
    result = dispatcher.dispatch_generation(
        user_id=user_id,
        request=request,
        plan_service=service,
        run_inline=True,
    )
    if result.plan is not None:
        return result.plan
    raise HTTPException(
        status_code=status.HTTP_202_ACCEPTED,
        detail={"job_id": result.job_id},
    )


@router.get("/{plan_id}", response_model=TrainingPlanSchema)
def get_plan(
    plan_id: int,
    claims: dict = Depends(get_current_user),
    service: PlanService = Depends(get_plan_service),
) -> TrainingPlanSchema:
    user_id = service.ensure_user(claims)
    try:
        plan = service.get_plan(user_id, plan_id)
    except PermissionError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Plan not found")
    if plan is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Plan not found")
    return plan


@router.patch("/{plan_id}", response_model=TrainingPlanSchema)
def update_plan(
    plan_id: int,
    request: TrainingPlanSchema,
    claims: dict = Depends(get_current_user),
    service: PlanService = Depends(get_plan_service),
) -> TrainingPlanSchema:
    fields = request.model_dump(exclude_none=True)
    user_id = service.ensure_user(claims)
    try:
        return service.update_plan(user_id, plan_id, **fields)
    except PermissionError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Plan not found")


@router.delete("/{plan_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def delete_plan(
    plan_id: int,
    claims: dict = Depends(get_current_user),
    service: PlanService = Depends(get_plan_service),
) -> Response:
    user_id = service.ensure_user(claims)
    try:
        service.delete_plan(user_id, plan_id)
    except PermissionError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Plan not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{plan_id}/adjust", response_model=TrainingPlanSchema)
def adjust_plan(
    plan_id: int,
    request: PlanAdjustmentRequest,
    claims: dict = Depends(get_current_user),
    service: PlanService = Depends(get_plan_service),
    dispatcher: PlanTaskDispatcher = Depends(get_plan_task_dispatcher),
) -> TrainingPlanSchema:
    user_id = service.ensure_user(claims)
    try:
        result = dispatcher.dispatch_adjustment(
            user_id=user_id,
            plan_id=plan_id,
            request=request,
            plan_service=service,
            run_inline=True,
        )
        if result.plan is not None:
            return result.plan
        raise HTTPException(
            status_code=status.HTTP_202_ACCEPTED,
            detail={"job_id": result.job_id},
        )
    except PermissionError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Plan not found")
