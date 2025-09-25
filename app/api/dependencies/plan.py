from fastapi import Depends
from sqlalchemy.orm import Session

from app.api.dependencies.db import get_db_session
from app.api.dependencies.strava import get_strava_activity_service
from app.core.config import Settings, get_settings
from app.services.plan_factory import create_plan_service
from app.services.plan_service import PlanService
from app.services.strava_api import StravaActivityService


def get_plan_service(
    db: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
    strava_service: StravaActivityService = Depends(get_strava_activity_service),
) -> PlanService:
    return create_plan_service(
        db,
        settings,
        strava_service=strava_service,
    )
