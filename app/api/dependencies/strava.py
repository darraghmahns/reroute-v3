from fastapi import Depends
from sqlalchemy.orm import Session

from app.api.dependencies.db import get_db_session
from app.core.config import Settings, get_settings
from app.repositories.strava import StravaCredentialRepository
from app.services.strava import StravaAuthService
from app.services.strava_api import StravaActivityService


def get_strava_activity_service(
    db: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> StravaActivityService:
    credential_repo = StravaCredentialRepository(db)
    auth_service = StravaAuthService(settings)
    return StravaActivityService(
        settings=settings,
        credential_repo=credential_repo,
        auth_service=auth_service,
    )
