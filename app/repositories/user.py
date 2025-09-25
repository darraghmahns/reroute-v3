from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.user import User


class UserRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_auth0_sub(self, sub: str) -> User | None:
        statement = select(User).where(User.auth0_sub == sub)
        return self._session.scalar(statement)

    def create_or_update_from_auth0(self, *, sub: str, email: str | None, name: str | None) -> User:
        existing = self.get_by_auth0_sub(sub)
        if existing:
            existing.email = email
            existing.name = name
            self._session.add(existing)
            self._session.commit()
            self._session.refresh(existing)
            return existing

        user = User(auth0_sub=sub, email=email, name=name)
        self._session.add(user)
        self._session.commit()
        self._session.refresh(user)
        return user

    def get_by_id(self, user_id: int) -> User | None:
        statement = select(User).where(User.id == user_id)
        return self._session.scalar(statement)

    def list_users(self, *, limit: int = 50, offset: int = 0) -> list[User]:
        statement = select(User).order_by(User.id).limit(limit).offset(offset)
        return list(self._session.scalars(statement))

    def update_user(self, user: User, **fields: object) -> User:
        for key, value in fields.items():
            if hasattr(user, key):
                setattr(user, key, value)
        self._session.add(user)
        self._session.commit()
        self._session.refresh(user)
        return user

    def deactivate_user(self, user: User) -> User:
        user.is_active = False
        user.deleted_at = datetime.utcnow()
        self._session.add(user)
        self._session.commit()
        self._session.refresh(user)
        return user
