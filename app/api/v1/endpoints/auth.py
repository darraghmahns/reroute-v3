from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_user
from app.api.dependencies.db import get_db_session
from app.repositories.strava import StravaCredentialRepository
from app.repositories.user import UserRepository
from app.schemas.user import AuthSessionResponse

router = APIRouter(prefix="/v1/auth", tags=["auth"])


@router.post("/session", response_model=AuthSessionResponse)
def create_session(
    claims: dict = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> AuthSessionResponse:
    user_repo = UserRepository(db)
    user = user_repo.create_or_update_from_auth0(
        sub=claims["sub"],
        email=claims.get("email"),
        name=claims.get("name"),
    )

    strava_repo = StravaCredentialRepository(db)
    strava_linked = strava_repo.get_by_user_id(user.id) is not None

    return AuthSessionResponse(
        user_id=user.id,
        auth0_sub=user.auth0_sub,
        email=user.email,
        name=user.name,
        strava_linked=strava_linked,
    )
