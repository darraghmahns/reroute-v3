from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.ai import AIExecutionLog


class AIExecutionLogRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def record(
        self,
        *,
        user_id: int,
        plan_id: int | None,
        job_type: str,
        model_name: str | None,
        prompt: str,
        response: str | None,
        tokens_used: int | None,
        cost_usd: float | None,
    ) -> AIExecutionLog:
        log = AIExecutionLog(
            user_id=user_id,
            plan_id=plan_id,
            job_type=job_type,
            model_name=model_name,
            prompt=prompt,
            response=response,
            tokens_used=tokens_used,
            cost_usd=cost_usd,
        )
        self._session.add(log)
        self._session.commit()
        self._session.refresh(log)
        return log
