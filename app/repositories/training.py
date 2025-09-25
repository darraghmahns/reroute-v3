from __future__ import annotations

from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.training import TrainingBlock, TrainingPlan, TrainingPlanRevision, Workout


class TrainingPlanRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create_plan(
        self,
        *,
        user_id: int,
        name: str | None = None,
        goal: str | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> TrainingPlan:
        plan = TrainingPlan(
            user_id=user_id,
            name=name,
            goal=goal,
            start_date=start_date,
            end_date=end_date,
        )
        self._session.add(plan)
        self._session.commit()
        self._session.refresh(plan)
        return plan

    def get_plan(self, plan_id: int) -> TrainingPlan | None:
        statement = select(TrainingPlan).where(TrainingPlan.id == plan_id)
        return self._session.scalar(statement)

    def list_plans_for_user(self, user_id: int) -> list[TrainingPlan]:
        statement = select(TrainingPlan).where(TrainingPlan.user_id == user_id).order_by(TrainingPlan.created_at.desc())
        return list(self._session.scalars(statement))

    def update_plan(self, plan: TrainingPlan, **fields: object) -> TrainingPlan:
        for key, value in fields.items():
            if hasattr(plan, key):
                setattr(plan, key, value)
        self._session.add(plan)
        self._session.commit()
        self._session.refresh(plan)
        return plan

    def add_revision(self, plan: TrainingPlan, change_summary: str | None) -> TrainingPlanRevision:
        next_version = self._session.scalar(
            select(func.coalesce(func.max(TrainingPlanRevision.version), 0)).where(TrainingPlanRevision.plan_id == plan.id)
        )
        next_version = int(next_version or 0) + 1
        revision = TrainingPlanRevision(plan_id=plan.id, version=next_version, change_summary=change_summary)
        self._session.add(revision)
        self._session.commit()
        self._session.refresh(revision)
        return revision

    def add_block(
        self,
        plan: TrainingPlan,
        *,
        name: str | None,
        focus: str | None,
        order_index: int,
        start_date: date | None,
        end_date: date | None,
    ) -> TrainingBlock:
        block = TrainingBlock(
            plan_id=plan.id,
            name=name,
            focus=focus,
            order_index=order_index,
            start_date=start_date,
            end_date=end_date,
        )
        self._session.add(block)
        self._session.commit()
        self._session.refresh(block)
        return block

    def add_workout(
        self,
        plan: TrainingPlan,
        *,
        block: TrainingBlock | None = None,
        scheduled_date: date | None = None,
        sport_type: str | None = None,
        name: str | None = None,
        description: str | None = None,
        duration_minutes: int | None = None,
        distance_km: float | None = None,
        target_intensity: str | None = None,
        target_tss: int | None = None,
    ) -> Workout:
        workout = Workout(
            plan_id=plan.id,
            block_id=block.id if block else None,
            scheduled_date=scheduled_date,
            sport_type=sport_type,
            name=name,
            description=description,
            duration_minutes=duration_minutes,
            distance_km=distance_km,
            target_intensity=target_intensity,
            target_tss=target_tss,
        )
        self._session.add(workout)
        self._session.commit()
        self._session.refresh(workout)
        return workout

    def list_workouts_for_plan(self, plan_id: int) -> list[Workout]:
        statement = select(Workout).where(Workout.plan_id == plan_id).order_by(Workout.scheduled_date)
        return list(self._session.scalars(statement))

    def delete_plan(self, plan: TrainingPlan) -> None:
        self._session.delete(plan)
        self._session.commit()
