from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

try:  # pragma: no cover - optional dependency
    import rq
    from redis import Redis
except ImportError:  # pragma: no cover - fall back to inline execution
    rq = None
    Redis = None

from app.core.config import Settings
from app.db.session import session_scope
from app.schemas.plan import ActivitySummary, PlanAdjustmentRequest, PlanGenerationRequest, TrainingPlanSchema
from app.services.plan_factory import create_plan_service
from app.services.plan_service import PlanService


@dataclass(slots=True)
class TaskResult:
    status: str
    plan: TrainingPlanSchema | None = None
    job_id: str | None = None


class PlanTaskDispatcher:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._queue = self._init_queue(settings)

    def _init_queue(self, settings: Settings):
        if settings.task_queue_force_inline:
            return None
        if settings.task_queue_url is None or rq is None or Redis is None:
            return None
        try:
            connection = Redis.from_url(settings.task_queue_url)
            return rq.Queue(
                settings.task_queue_name,
                connection=connection,
                default_timeout=settings.task_queue_job_timeout_seconds,
            )
        except Exception:  # pragma: no cover - redis not reachable
            return None

    @property
    def supports_queue(self) -> bool:
        return self._queue is not None

    def dispatch_generation(
        self,
        *,
        user_id: int,
        request: PlanGenerationRequest,
        plan_service: PlanService | None = None,
        run_inline: bool = False,
    ) -> TaskResult:
        if run_inline or self._queue is None:
            plan = self._execute_inline(lambda svc: svc.generate_plan_for_user(user_id, request), plan_service)
            return TaskResult(status="completed", plan=plan)

        job = self._queue.enqueue(  # type: ignore[union-attr]
            "app.tasks.plan_jobs.generate_plan_job",
            user_id,
            request.model_dump(mode="json"),
            job_timeout=self._settings.task_queue_job_timeout_seconds,
        )
        return TaskResult(status="queued", job_id=job.id)

    def dispatch_adjustment(
        self,
        *,
        user_id: int,
        plan_id: int,
        request: PlanAdjustmentRequest,
        plan_service: PlanService | None = None,
        activity: ActivitySummary | None = None,
        run_inline: bool = False,
    ) -> TaskResult:
        if run_inline or self._queue is None:
            plan = self._execute_inline(
                lambda svc: svc.adjust_plan(user_id, plan_id, request, activity),
                plan_service,
            )
            return TaskResult(status="completed", plan=plan)

        job = self._queue.enqueue(  # type: ignore[union-attr]
            "app.tasks.plan_jobs.adjust_plan_job",
            user_id,
            plan_id,
            request.model_dump(mode="json"),
            activity.model_dump(mode="json") if activity else None,
            job_timeout=self._settings.task_queue_job_timeout_seconds,
        )
        return TaskResult(status="queued", job_id=job.id)

    def _execute_inline(
        self,
        func: Callable[[PlanService], TrainingPlanSchema],
        plan_service: PlanService | None,
    ) -> TrainingPlanSchema:
        if plan_service is not None:
            return func(plan_service)

        with session_scope() as session:
            service = create_plan_service(session, self._settings)
            plan_schema = func(service)
            session.expunge_all()
            return plan_schema
