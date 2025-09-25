from __future__ import annotations

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.api.dependencies.db import get_db_session
from app.models.user import User
from app.repositories.user import UserRepository
from app.security.auth0 import Auth0TokenVerifier


def get_token_verifier(settings: Settings = Depends(get_settings)) -> Auth0TokenVerifier:
    return Auth0TokenVerifier(settings=settings)


def get_current_user(
    authorization: str | None = Header(default=None, alias="Authorization"),
    verifier: Auth0TokenVerifier = Depends(get_token_verifier),
) -> dict:
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header",
        )

    try:
        scheme, token = authorization.split(" ", 1)
    except ValueError as exc:  # pragma: no cover - defensive
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Malformed Authorization header",
        ) from exc

    if scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header must start with Bearer",
        )

    try:
        return verifier.verify(token)
    except Auth0TokenVerifier.TokenVerificationError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        ) from exc


def require_admin_user(
    claims: dict = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> "User":
    repo = UserRepository(db)
    user = repo.get_by_auth0_sub(claims["sub"])
    if user is None:
        user = repo.create_or_update_from_auth0(
            sub=claims["sub"],
            email=claims.get("email"),
            name=claims.get("name"),
        )
    if user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin privileges required")
    return user
