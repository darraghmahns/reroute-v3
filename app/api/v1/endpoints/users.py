from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_user, require_admin_user
from app.api.dependencies.db import get_db_session
from app.models.user import User
from app.repositories.user import UserRepository
from app.schemas.user import UserCreateAdmin, UserResponse, UserUpdateAdmin, UserUpdateSelf

router = APIRouter(prefix="/v1/users", tags=["users"])


def _user_to_response(user) -> UserResponse:
    return UserResponse.model_validate(user.as_dict())


@router.get("/me", response_model=UserResponse)
def read_current_user(
    claims: dict = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> UserResponse:
    repo = UserRepository(db)
    user = repo.create_or_update_from_auth0(
        sub=claims["sub"],
        email=claims.get("email"),
        name=claims.get("name"),
    )
    if claims.get("timezone") and user.timezone != claims["timezone"]:
        repo.update_user(user, timezone=claims["timezone"])
    return _user_to_response(user)


@router.patch("/me", response_model=UserResponse)
def update_current_user(
    payload: UserUpdateSelf,
    claims: dict = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> UserResponse:
    repo = UserRepository(db)
    user = repo.create_or_update_from_auth0(
        sub=claims["sub"],
        email=claims.get("email"),
        name=claims.get("name"),
    )
    updates: dict[str, Any] = {}
    if payload.name is not None:
        updates["name"] = payload.name
    if payload.timezone is not None:
        updates["timezone"] = payload.timezone
    if updates:
        user = repo.update_user(user, **updates)
    return _user_to_response(user)


@router.get("/", response_model=list[UserResponse])
def list_users(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    admin_user: User = Depends(require_admin_user),
    db: Session = Depends(get_db_session),
) -> list[UserResponse]:
    repo = UserRepository(db)
    users = repo.list_users(limit=limit, offset=offset)
    return [_user_to_response(user) for user in users]


@router.post("/", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def create_user_admin(
    payload: UserCreateAdmin,
    admin_user: User = Depends(require_admin_user),
    db: Session = Depends(get_db_session),
) -> UserResponse:
    repo = UserRepository(db)
    existing = repo.get_by_auth0_sub(payload.auth0_sub)
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="User already exists")
    user = repo.create_or_update_from_auth0(
        sub=payload.auth0_sub,
        email=payload.email,
        name=payload.name,
    )
    user = repo.update_user(user, role=payload.role, timezone=payload.timezone)
    return _user_to_response(user)


@router.get("/{user_id}", response_model=UserResponse)
def get_user_admin(
    user_id: int,
    admin_user: User = Depends(require_admin_user),
    db: Session = Depends(get_db_session),
) -> UserResponse:
    repo = UserRepository(db)
    user = repo.get_by_id(user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return _user_to_response(user)


@router.patch("/{user_id}", response_model=UserResponse)
def update_user_admin(
    user_id: int,
    payload: UserUpdateAdmin,
    admin_user: User = Depends(require_admin_user),
    db: Session = Depends(get_db_session),
) -> UserResponse:
    repo = UserRepository(db)
    user = repo.get_by_id(user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    updates: dict[str, Any] = {}
    if payload.name is not None:
        updates["name"] = payload.name
    if payload.email is not None:
        updates["email"] = payload.email
    if payload.timezone is not None:
        updates["timezone"] = payload.timezone
    if payload.role is not None:
        updates["role"] = payload.role
    if payload.is_active is not None:
        updates["is_active"] = payload.is_active
        if payload.is_active:
            updates["deleted_at"] = None
    if updates:
        user = repo.update_user(user, **updates)
    return _user_to_response(user)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def deactivate_user_admin(
    user_id: int,
    admin_user: User = Depends(require_admin_user),
    db: Session = Depends(get_db_session),
) -> None:
    repo = UserRepository(db)
    user = repo.get_by_id(user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    repo.deactivate_user(user)
