from datetime import datetime

from sqlalchemy import DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class StravaCredential(Base):
    __tablename__ = "strava_credentials"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True)
    athlete_id: Mapped[int] = mapped_column(unique=True, index=True)
    access_token: Mapped[str]
    refresh_token: Mapped[str]
    token_type: Mapped[str]
    scope: Mapped[str]
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    user = relationship("User", backref="strava_credential", lazy="joined")
