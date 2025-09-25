from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings, get_settings
from app.models.base import Base

_ENGINE = None
_SessionLocal: sessionmaker[Session] | None = None


def init_engine(settings: Settings | None = None) -> None:
    global _ENGINE, _SessionLocal
    settings = settings or get_settings()
    database_url = getattr(settings, "database_url", None)
    if not database_url:
        raise RuntimeError("DATABASE_URL is not configured")

    _ENGINE = create_engine(database_url, future=True)
    if settings.app_env == "test":
        Base.metadata.create_all(_ENGINE)
    _SessionLocal = sessionmaker(bind=_ENGINE, expire_on_commit=False, class_=Session)


@contextmanager
def session_scope() -> Iterator[Session]:
    if _SessionLocal is None:
        init_engine()
    assert _SessionLocal is not None
    session = _SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
