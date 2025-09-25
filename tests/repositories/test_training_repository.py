from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import training as training_models  # noqa: F401 ensure metadata
from app.models import user as user_models  # noqa: F401 ensure metadata
from app.models.base import Base
from app.repositories.training import TrainingPlanRepository
from app.repositories.user import UserRepository


def _setup_session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return Session(engine)


def test_create_plan_with_blocks_and_workouts() -> None:
    session = _setup_session()
    repo = TrainingPlanRepository(session)
    user_repo = UserRepository(session)

    user = user_repo.create_or_update_from_auth0(sub="auth0|user", email="user@example.com", name="Athlete")

    plan = repo.create_plan(user_id=user.id, name="Base", goal="Build endurance", start_date=date(2025, 9, 1))
    assert plan.id is not None

    block = repo.add_block(
        plan,
        name="Base 1",
        focus="Endurance",
        order_index=1,
        start_date=date(2025, 9, 1),
        end_date=date(2025, 9, 21),
    )

    workout = repo.add_workout(
        plan,
        block=block,
        scheduled_date=date(2025, 9, 2),
        sport_type="ride",
        name="Sweet spot intervals",
        duration_minutes=90,
        target_intensity="sweet_spot",
        target_tss=80,
    )

    assert workout.id is not None

    revision = repo.add_revision(plan, change_summary="Initial plan created")
    assert revision.version == 1

    workouts = repo.list_workouts_for_plan(plan.id)
    assert len(workouts) == 1

    session.close()


def test_update_and_delete_plan() -> None:
    session = _setup_session()
    repo = TrainingPlanRepository(session)
    user_repo = UserRepository(session)

    user = user_repo.create_or_update_from_auth0(sub="auth0|user", email="user@example.com", name="Athlete")
    plan = repo.create_plan(user_id=user.id, name="Base", goal="Build endurance")

    updated = repo.update_plan(plan, status="active", goal="Prepare for race")
    assert updated.status == "active"
    assert updated.goal == "Prepare for race"

    repo.delete_plan(updated)
    assert repo.get_plan(updated.id) is None

    session.close()
