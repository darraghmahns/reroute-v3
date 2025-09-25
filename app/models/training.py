from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class TrainingPlan(Base):
    __tablename__ = "training_plans"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    name: Mapped[str | None] = mapped_column(String(255))
    goal: Mapped[str | None] = mapped_column(Text)
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(32), default="draft")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    blocks: Mapped[list[TrainingBlock]] = relationship("TrainingBlock", back_populates="plan", cascade="all, delete-orphan")
    workouts: Mapped[list[Workout]] = relationship("Workout", back_populates="plan", cascade="all, delete-orphan")
    revisions: Mapped[list[TrainingPlanRevision]] = relationship("TrainingPlanRevision", back_populates="plan", cascade="all, delete-orphan")


class TrainingBlock(Base):
    __tablename__ = "training_blocks"

    plan_id: Mapped[int] = mapped_column(ForeignKey("training_plans.id"))
    name: Mapped[str | None] = mapped_column(String(255))
    focus: Mapped[str | None] = mapped_column(String(255))
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    plan: Mapped[TrainingPlan] = relationship("TrainingPlan", back_populates="blocks")
    workouts: Mapped[list[Workout]] = relationship("Workout", back_populates="block")


class Workout(Base):
    __tablename__ = "workouts"

    plan_id: Mapped[int] = mapped_column(ForeignKey("training_plans.id"))
    block_id: Mapped[int | None] = mapped_column(ForeignKey("training_blocks.id"), nullable=True)
    scheduled_date: Mapped[date | None] = mapped_column(Date)
    sport_type: Mapped[str | None] = mapped_column(String(50))  # e.g. ride, run, swim
    name: Mapped[str | None] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    duration_minutes: Mapped[int | None] = mapped_column(Integer)
    distance_km: Mapped[float | None] = mapped_column(Float)
    target_intensity: Mapped[str | None] = mapped_column(String(50))
    target_tss: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    plan: Mapped[TrainingPlan] = relationship("TrainingPlan", back_populates="workouts")
    block: Mapped[TrainingBlock | None] = relationship("TrainingBlock", back_populates="workouts")


class TrainingPlanRevision(Base):
    __tablename__ = "training_plan_revisions"

    plan_id: Mapped[int] = mapped_column(ForeignKey("training_plans.id"))
    version: Mapped[int] = mapped_column(Integer)
    change_summary: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    plan: Mapped[TrainingPlan] = relationship("TrainingPlan", back_populates="revisions")
