from fastapi import Depends

from app.core.config import Settings, get_settings
from app.services.task_dispatcher import PlanTaskDispatcher


def get_plan_task_dispatcher(settings: Settings = Depends(get_settings)) -> PlanTaskDispatcher:
    return PlanTaskDispatcher(settings)
