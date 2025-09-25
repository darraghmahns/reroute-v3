from collections.abc import Iterator

from fastapi import Depends
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.session import init_engine, session_scope


def get_db_session(settings: Settings = Depends(get_settings)) -> Iterator[Session]:
    init_engine(settings)
    with session_scope() as session:
        yield session
