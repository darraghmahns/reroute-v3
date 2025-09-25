from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.dependencies.auth import get_current_user
from app.api.dependencies.db import get_db_session
from app.api.dependencies.plan import get_plan_service
from app.api.dependencies.tasks import get_plan_task_dispatcher
from app.main import app
from app.models import training as training_models  # noqa: F401 ensure metadata
from app.models import user as user_models  # noqa: F401 ensure metadata
from app.models.base import Base
from app.ai.plan_agent import PlanAgent
from app.repositories.user import UserRepository
from app.repositories.training import TrainingPlanRepository
from app.services.plan_service import PlanService
from app.services.task_dispatcher import TaskResult
from app.schemas.plan import PlanAdjustmentRequest, PlanGenerationRequest


@pytest.fixture()
def db_override():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, class_=Session)

    def _provide_session():
        with SessionLocal() as session:
            yield session

    app.dependency_overrides[get_db_session] = _provide_session

    def _plan_service_override():
        with SessionLocal() as session:
            plan_repo = TrainingPlanRepository(session)
            user_repo = UserRepository(session)
            agent = PlanAgent()
            yield PlanService(session, plan_repo, user_repo, agent)

    app.dependency_overrides[get_plan_service] = _plan_service_override

    class _InlineDispatcher:
        def __init__(self, session_factory: sessionmaker) -> None:
            self.generation_calls: list[tuple[int, PlanGenerationRequest]] = []
            self.adjust_calls: list[tuple[int, int, PlanAdjustmentRequest]] = []
            self._session_factory = session_factory

        def dispatch_generation(self, *, user_id, request, plan_service=None, run_inline=False, **_):
            if plan_service is None:
                with self._session_factory() as session:
                    plan_repo = TrainingPlanRepository(session)
                    user_repo = UserRepository(session)
                    agent = PlanAgent()
                    plan_service = PlanService(session, plan_repo, user_repo, agent)
                    plan = plan_service.generate_plan_for_user(user_id, request)
            else:
                plan = plan_service.generate_plan_for_user(user_id, request)
            if isinstance(request, PlanGenerationRequest):
                self.generation_calls.append((user_id, request))
            return TaskResult(status="completed", plan=plan)

        def dispatch_adjustment(
            self,
            *,
            user_id,
            plan_id,
            request,
            plan_service=None,
            activity=None,
            run_inline=False,
            **_,
        ):
            if plan_service is None:
                with self._session_factory() as session:
                    plan_repo = TrainingPlanRepository(session)
                    user_repo = UserRepository(session)
                    agent = PlanAgent()
                    plan_service = PlanService(session, plan_repo, user_repo, agent)
                    plan = plan_service.adjust_plan(user_id, plan_id, request, activity)
            else:
                plan = plan_service.adjust_plan(user_id, plan_id, request, activity)
            if isinstance(request, PlanAdjustmentRequest):
                self.adjust_calls.append((user_id, plan_id, request))
            return TaskResult(status="completed", plan=plan)

    inline_dispatcher = _InlineDispatcher(SessionLocal)

    def _dispatcher_override():
        return inline_dispatcher

    app.dependency_overrides[get_plan_task_dispatcher] = _dispatcher_override
    app.state.test_plan_dispatcher = inline_dispatcher

    yield SessionLocal

    app.dependency_overrides.pop(get_db_session, None)
    app.dependency_overrides.pop(get_plan_service, None)
    app.dependency_overrides.pop(get_plan_task_dispatcher, None)
    app.state.__dict__.pop("test_plan_dispatcher", None)


@pytest.fixture()
def client(db_override):
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def override_current_user(db_override):
    SessionLocal: sessionmaker = db_override  # type: ignore[assignment]

    def _mock_current_user(authorization: str | None = None):
        with SessionLocal() as session:
            repo = UserRepository(session)
            user = repo.create_or_update_from_auth0(
                sub="auth0|user",
                email="user@example.com",
                name="Athlete",
            )
            if user.timezone != "UTC":
                repo.update_user(user, timezone="UTC")
        return {
            "sub": "auth0|user",
            "email": "user@example.com",
            "name": "Athlete",
        }

    app.dependency_overrides[get_current_user] = _mock_current_user

    yield

    app.dependency_overrides.pop(get_current_user, None)


def test_generate_plan(client):
    payload = {"goal": "Build endurance", "duration_weeks": 4, "start_date": "2025-09-01"}
    response = client.post("/v1/plans/generate", json=payload)
    assert response.status_code == 201
    body = response.json()
    assert body["goal"] == "Build endurance"
    assert len(body["blocks"]) >= 1


def test_list_and_get_plan(client):
    client.post("/v1/plans/generate", json={"goal": "Base", "duration_weeks": 2})
    list_response = client.get("/v1/plans")
    assert list_response.status_code == 200
    plans = list_response.json()
    assert len(plans) >= 1

    plan_id = 1
    detail_response = client.get(f"/v1/plans/{plan_id}")
    assert detail_response.status_code == 200


def test_update_plan(client):
    client.post("/v1/plans/generate", json={"goal": "Base", "duration_weeks": 2})
    response = client.patch(
        "/v1/plans/1",
        json={"goal": "Updated goal", "status": "active"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["goal"] == "Updated goal"
    assert body["status"] == "active"


def test_adjust_plan(client):
    client.post("/v1/plans/generate", json={"goal": "Base", "duration_weeks": 2})
    response = client.post(
        "/v1/plans/1/adjust",
        json={"reason": "Post workout adjustment"},
    )
    assert response.status_code == 200


def test_delete_plan(client):
    client.post("/v1/plans/generate", json={"goal": "Base", "duration_weeks": 2})
    response = client.delete("/v1/plans/1")
    assert response.status_code == 204
