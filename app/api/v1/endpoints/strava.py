from fastapi import APIRouter, Cookie, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_user
from app.api.dependencies.db import get_db_session
from app.api.dependencies.strava import get_strava_activity_service
from app.api.dependencies.tasks import get_plan_task_dispatcher
from app.core.config import Settings, get_settings
from app.repositories.strava import StravaCredentialRepository
from app.repositories.training import TrainingPlanRepository
from app.repositories.user import UserRepository
from app.schemas.plan import PlanAdjustmentRequest
from app.schemas.strava import (
    StravaActivityDetail,
    StravaActivitySummary,
    StravaAthleteProfile,
    StravaAthleteStats,
    StravaAuthorizeResponse,
    StravaRouteSummary,
    StravaSegmentSummary,
    StravaTokenExchangeResponse,
    StravaStream,
    StravaWebhookEvent,
)
from app.services.strava import StravaAuthError, StravaAuthService
from app.services.strava_api import StravaAPIError, StravaActivityService
from app.services.task_dispatcher import PlanTaskDispatcher

router = APIRouter(prefix="/v1/integrations/strava", tags=["strava"])


@router.get("/connect", response_model=StravaAuthorizeResponse)
def connect_strava(
    response: Response,
    settings: Settings = Depends(get_settings),
) -> StravaAuthorizeResponse:
    service = StravaAuthService(settings)
    state = service.generate_state()
    authorize_url = service.build_authorize_url(state)

    secure_cookie = settings.app_env == "production"

    response.set_cookie(
        key="strava_oauth_state",
        value=state,
        max_age=600,
        httponly=True,
        secure=secure_cookie,
        samesite="lax",
    )

    return StravaAuthorizeResponse(authorize_url=authorize_url)


@router.get("/callback", response_model=StravaTokenExchangeResponse)
def strava_callback(
    response: Response,
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    state_cookie: str | None = Cookie(default=None, alias="strava_oauth_state"),
    settings: Settings = Depends(get_settings),
    claims: dict = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> StravaTokenExchangeResponse:
    if state_cookie is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing state cookie")

    if state is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing state")

    if state != state_cookie:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="State mismatch")

    if code is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing code")

    service = StravaAuthService(settings)

    try:
        token_response = service.exchange_code_for_tokens(code)
    except StravaAuthError as exc:
        response.delete_cookie("strava_oauth_state", path="/")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Strava token exchange failed",
        ) from exc

    user_repo = UserRepository(db)
    user = user_repo.create_or_update_from_auth0(
        sub=claims["sub"],
        email=claims.get("email"),
        name=claims.get("name"),
    )

    credential_repo = StravaCredentialRepository(db)
    credential_repo.upsert_from_token_exchange(
        user_id=user.id,
        athlete_id=token_response.athlete_id,
        access_token=token_response.access_token,
        refresh_token=token_response.refresh_token,
        token_type=token_response.token_type,
        scope=token_response.scope,
        expires_at=token_response.expires_at,
    )

    response.delete_cookie("strava_oauth_state", path="/")
    return token_response


@router.get("/activities", response_model=list[StravaActivitySummary])
def list_activities(
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=30, ge=1, le=200),
    claims: dict = Depends(get_current_user),
    db: Session = Depends(get_db_session),
    activity_service: StravaActivityService = Depends(get_strava_activity_service),
) -> list[StravaActivitySummary]:
    user_repo = UserRepository(db)
    user = user_repo.get_by_auth0_sub(claims["sub"])
    if user is None:
        user = user_repo.create_or_update_from_auth0(
            sub=claims["sub"],
            email=claims.get("email"),
            name=claims.get("name"),
        )

    try:
        activities = activity_service.list_activities(
            user_id=user.id,
            page=page,
            per_page=per_page,
        )
    except StravaAPIError as exc:
        if exc.status_code == 404:
            detail = "Strava activity not found" if "activity" in exc.message.lower() else "Strava account not linked"
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail) from exc
        if exc.status_code == 429:
            raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Strava rate limited") from exc
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Strava API failure") from exc

    return [StravaActivitySummary.model_validate(item) for item in activities]


@router.get("/activities/{activity_id}", response_model=StravaActivityDetail)
def get_activity(
    activity_id: int,
    include_all_efforts: bool = Query(default=False),
    claims: dict = Depends(get_current_user),
    db: Session = Depends(get_db_session),
    activity_service: StravaActivityService = Depends(get_strava_activity_service),
) -> StravaActivityDetail:
    user_repo = UserRepository(db)
    user = user_repo.get_by_auth0_sub(claims["sub"])
    if user is None:
        user = user_repo.create_or_update_from_auth0(
            sub=claims["sub"],
            email=claims.get("email"),
            name=claims.get("name"),
        )

    credential_repo = StravaCredentialRepository(db)
    has_credential = credential_repo.get_by_user_id(user.id) is not None

    try:
        activity = activity_service.get_activity(
            user_id=user.id,
            activity_id=activity_id,
            include_all_efforts=include_all_efforts,
        )
    except StravaAPIError as exc:
        if exc.status_code == 404:
            detail = "Strava account not linked"
            if has_credential:
                detail = "Strava activity not found"
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail) from exc
        if exc.status_code == 429:
            raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Strava rate limited") from exc
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Strava API failure") from exc

    return StravaActivityDetail.model_validate(activity)


DEFAULT_STREAM_KEYS = ["time", "distance", "heartrate", "cadence", "watts", "moving"]


@router.get("/activities/{activity_id}/streams", response_model=dict[str, StravaStream])
def get_activity_streams(
    activity_id: int,
    keys: str | None = Query(
        default=None,
        description="Comma-separated stream types (defaults to time,distance,heartrate,cadence,watts,moving)",
    ),
    key_by_type: bool = Query(default=True),
    claims: dict = Depends(get_current_user),
    db: Session = Depends(get_db_session),
    activity_service: StravaActivityService = Depends(get_strava_activity_service),
) -> dict[str, StravaStream]:
    user_repo = UserRepository(db)
    user = user_repo.get_by_auth0_sub(claims["sub"])
    if user is None:
        user = user_repo.create_or_update_from_auth0(
            sub=claims["sub"],
            email=claims.get("email"),
            name=claims.get("name"),
        )

    credential_repo = StravaCredentialRepository(db)
    has_credential = credential_repo.get_by_user_id(user.id) is not None

    if keys is None:
        key_list = DEFAULT_STREAM_KEYS
    else:
        key_list = [part.strip() for part in keys.split(",") if part.strip()]
    if not key_list:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="keys parameter required")

    try:
        streams = activity_service.get_activity_streams(
            user_id=user.id,
            activity_id=activity_id,
            keys=key_list,
            key_by_type=key_by_type,
        )
    except StravaAPIError as exc:
        if exc.status_code == 404:
            detail = "Strava account not linked"
            if has_credential:
                detail = "Strava activity not found"
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail) from exc
        if exc.status_code == 429:
            raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Strava rate limited") from exc
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Strava API failure") from exc

    if key_by_type and isinstance(streams, dict):
        normalized: dict[str, StravaStream] = {}
        for key, value in streams.items():
            if isinstance(value, dict) and "type" not in value:
                value = {**value, "type": key}
            normalized[key] = StravaStream.model_validate(value)
        return normalized

    if isinstance(streams, list):
        return {stream.get("type", str(index)): StravaStream.model_validate(stream) for index, stream in enumerate(streams)}

    raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Unexpected stream payload")


@router.get("/athlete/profile", response_model=StravaAthleteProfile)
def get_athlete_profile(
    claims: dict = Depends(get_current_user),
    db: Session = Depends(get_db_session),
    activity_service: StravaActivityService = Depends(get_strava_activity_service),
) -> StravaAthleteProfile:
    user_repo = UserRepository(db)
    user = user_repo.create_or_update_from_auth0(
        sub=claims["sub"],
        email=claims.get("email"),
        name=claims.get("name"),
    )

    try:
        profile = activity_service.get_athlete_profile(user.id)
    except StravaAPIError as exc:
        if exc.status_code == 404:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Strava account not linked") from exc
        if exc.status_code == 429:
            raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Strava rate limited") from exc
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Strava API failure") from exc

    return StravaAthleteProfile.model_validate(profile)


@router.get("/athlete/stats", response_model=StravaAthleteStats)
def get_athlete_stats(
    claims: dict = Depends(get_current_user),
    db: Session = Depends(get_db_session),
    activity_service: StravaActivityService = Depends(get_strava_activity_service),
) -> StravaAthleteStats:
    user_repo = UserRepository(db)
    user = user_repo.create_or_update_from_auth0(
        sub=claims["sub"],
        email=claims.get("email"),
        name=claims.get("name"),
    )

    try:
        stats = activity_service.get_athlete_stats(user.id)
    except StravaAPIError as exc:
        if exc.status_code == 404:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Strava account not linked") from exc
        if exc.status_code == 429:
            raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Strava rate limited") from exc
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Strava API failure") from exc

    return StravaAthleteStats.model_validate(stats)


@router.get("/segments/starred", response_model=list[StravaSegmentSummary])
def list_starred_segments(
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=30, ge=1, le=200),
    claims: dict = Depends(get_current_user),
    db: Session = Depends(get_db_session),
    activity_service: StravaActivityService = Depends(get_strava_activity_service),
) -> list[StravaSegmentSummary]:
    user_repo = UserRepository(db)
    user = user_repo.create_or_update_from_auth0(
        sub=claims["sub"],
        email=claims.get("email"),
        name=claims.get("name"),
    )

    try:
        segments = activity_service.list_starred_segments(user.id, page=page, per_page=per_page)
    except StravaAPIError as exc:
        if exc.status_code == 404:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Strava account not linked") from exc
        if exc.status_code == 429:
            raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Strava rate limited") from exc
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Strava API failure") from exc

    return [StravaSegmentSummary.model_validate(segment) for segment in segments]


@router.get("/segments/explore", response_model=list[StravaSegmentSummary])
def explore_segments(
    bounds: str = Query(..., description="Comma-separated lat/lng bounds: southwest_lat,southwest_lng,northeast_lat,northeast_lng"),
    activity_type: str | None = Query(default=None),
    claims: dict = Depends(get_current_user),
    db: Session = Depends(get_db_session),
    activity_service: StravaActivityService = Depends(get_strava_activity_service),
) -> list[StravaSegmentSummary]:
    user_repo = UserRepository(db)
    user = user_repo.create_or_update_from_auth0(
        sub=claims["sub"],
        email=claims.get("email"),
        name=claims.get("name"),
    )

    try:
        segments = activity_service.explore_segments(user.id, bounds=bounds, activity_type=activity_type)
    except StravaAPIError as exc:
        if exc.status_code == 404:
            return []
        if exc.status_code == 429:
            raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Strava rate limited") from exc
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Strava API failure") from exc

    return [StravaSegmentSummary.model_validate(segment) for segment in segments]


@router.get("/segments/{segment_id}", response_model=StravaSegmentSummary)
def get_segment(
    segment_id: int,
    claims: dict = Depends(get_current_user),
    db: Session = Depends(get_db_session),
    activity_service: StravaActivityService = Depends(get_strava_activity_service),
) -> StravaSegmentSummary:
    user_repo = UserRepository(db)
    user = user_repo.create_or_update_from_auth0(
        sub=claims["sub"],
        email=claims.get("email"),
        name=claims.get("name"),
    )

    try:
        segment = activity_service.get_segment(user.id, segment_id)
    except StravaAPIError as exc:
        if exc.status_code == 404:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Strava segment not found") from exc
        if exc.status_code == 429:
            raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Strava rate limited") from exc
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Strava API failure") from exc

    return StravaSegmentSummary.model_validate(segment)


@router.get("/routes", response_model=list[StravaRouteSummary])
def list_routes(
    claims: dict = Depends(get_current_user),
    db: Session = Depends(get_db_session),
    activity_service: StravaActivityService = Depends(get_strava_activity_service),
) -> list[StravaRouteSummary]:
    user_repo = UserRepository(db)
    user = user_repo.create_or_update_from_auth0(
        sub=claims["sub"],
        email=claims.get("email"),
        name=claims.get("name"),
    )

    try:
        routes = activity_service.list_routes(user.id)
    except StravaAPIError as exc:
        if exc.status_code == 404:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Strava account not linked") from exc
        if exc.status_code == 429:
            raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Strava rate limited") from exc
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Strava API failure") from exc

    return [StravaRouteSummary.model_validate(route) for route in routes]


@router.get("/routes/{route_id}", response_model=StravaRouteSummary)
def get_route(
    route_id: int,
    claims: dict = Depends(get_current_user),
    db: Session = Depends(get_db_session),
    activity_service: StravaActivityService = Depends(get_strava_activity_service),
) -> StravaRouteSummary:
    user_repo = UserRepository(db)
    user = user_repo.create_or_update_from_auth0(
        sub=claims["sub"],
        email=claims.get("email"),
        name=claims.get("name"),
    )

    try:
        route = activity_service.get_route(user.id, route_id)
    except StravaAPIError as exc:
        if exc.status_code == 404:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Strava route not found") from exc
        if exc.status_code == 429:
            raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Strava rate limited") from exc
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Strava API failure") from exc

    return StravaRouteSummary.model_validate(route)


@router.get("/routes/{route_id}/streams", response_model=dict[str, StravaStream])
def get_route_streams(
    route_id: int,
    keys: str | None = Query(default=None, description="Comma-separated stream types (e.g. latlng,elevation)"),
    claims: dict = Depends(get_current_user),
    db: Session = Depends(get_db_session),
    activity_service: StravaActivityService = Depends(get_strava_activity_service),
) -> dict[str, StravaStream]:
    user_repo = UserRepository(db)
    user = user_repo.create_or_update_from_auth0(
        sub=claims["sub"],
        email=claims.get("email"),
        name=claims.get("name"),
    )

    key_list = [part.strip() for part in keys.split(",")] if keys else None

    try:
        streams = activity_service.get_route_streams(user.id, route_id, keys=key_list)
    except StravaAPIError as exc:
        if exc.status_code == 404:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Strava route not found") from exc
        if exc.status_code == 429:
            raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Strava rate limited") from exc
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Strava API failure") from exc

    if isinstance(streams, dict):
        return {k: StravaStream.model_validate(v) for k, v in streams.items()}
    if isinstance(streams, list):
        return {stream.get("type", str(index)): StravaStream.model_validate(stream) for index, stream in enumerate(streams)}
    raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Unexpected stream payload")


@router.post("/webhook", status_code=status.HTTP_202_ACCEPTED)
def strava_webhook(
    event: StravaWebhookEvent,
    db: Session = Depends(get_db_session),
    dispatcher: PlanTaskDispatcher = Depends(get_plan_task_dispatcher),
) -> dict[str, object]:
    if event.object_type.lower() != "activity":
        return {"status": "ignored", "reason": "non-activity"}

    credential_repo = StravaCredentialRepository(db)
    credential = credential_repo.get_by_athlete_id(event.owner_id)
    if credential is None:
        return {"status": "ignored", "reason": "unknown-athlete"}

    plan_repo = TrainingPlanRepository(db)
    plans = plan_repo.list_plans_for_user(credential.user_id)
    if not plans:
        return {"status": "no-plan"}

    adjust_request = PlanAdjustmentRequest(
        reason=f"Strava {event.aspect_type} event for activity {event.object_id}",
    )

    results: list[dict[str, object]] = []
    for plan in plans:
        task_result = dispatcher.dispatch_adjustment(
            user_id=credential.user_id,
            plan_id=plan.id,
            request=adjust_request,
            run_inline=False,
        )
        results.append(
            {
                "plan_id": plan.id,
                "job_id": task_result.job_id,
                "status": task_result.status,
            }
        )

    overall_status = "queued" if any(result["status"] == "queued" for result in results) else "completed"
    return {
        "status": overall_status,
        "plans": results,
    }
