from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Callable

try:  # pragma: no cover - optional dependency
    from pydantic_ai import Agent as PydanticAgent
    from pydantic_ai.run import AgentRunResult
    from pydantic_ai.usage import RunUsage
    try:
        from pydantic_ai.models.openai import OpenAIChatModel as PydanticOpenAIModel
    except ImportError:  # pragma: no cover - backwards compatibility
        from pydantic_ai.models.openai import OpenAIModel as PydanticOpenAIModel
    from pydantic_ai.models.openai import OpenAIModelSettings
    from pydantic_ai.providers.openai import OpenAIProvider
except ImportError:  # pragma: no cover - allow heuristic fallback when library missing
    PydanticAgent = None  # type: ignore[assignment]
    AgentRunResult = Any  # type: ignore[assignment]
    RunUsage = Any  # type: ignore[assignment]
    PydanticOpenAIModel = Any  # type: ignore[assignment]
    OpenAIModelSettings = dict  # type: ignore[assignment]
    OpenAIProvider = Any  # type: ignore[assignment]

from app.schemas.plan import (
    PlanAdjustmentContext,
    PlanGenerationContext,
    TrainingBlockSchema,
    TrainingPlanSchema,
    WorkoutSchema,
)


PLAN_GENERATION_SYSTEM_PROMPT = (
    "You are an expert cycling coach. Generate structured JSON plans that align with the athlete profile, "
    "Strava history, and goal. Respect recovery needs, distribute intensity, and use Strava terminology for "
    "workout types."
)

PLAN_ADJUSTMENT_SYSTEM_PROMPT = (
    "You are an expert cycling coach adjusting an existing plan after reviewing the latest activity and metrics. "
    "Respond with an updated plan JSON that keeps previous structure but adjusts workouts when needed."
)


@dataclass(slots=True)
class AgentInvocationResult:
    plan: TrainingPlanSchema
    prompt: str
    messages_json: str | None
    usage: RunUsage | None
    model_name: str | None
    fallback_used: bool = False
    error: str | None = None


class PlanAgent:
    """AI-backed plan generator/adjuster with heuristic fallback."""

    def __init__(
        self,
        *,
        model_name: str | None = None,
        temperature: float = 0.3,
        max_output_tokens: int | None = 1200,
        openai_client: Any | None = None,
    ) -> None:
        self._model_name = model_name
        self._temperature = temperature
        self._max_output_tokens = max_output_tokens
        self._openai_client = openai_client
        self._generation_agent: PydanticAgent | None = None
        self._adjust_agent: PydanticAgent | None = None

        if PydanticAgent and openai_client is not None and hasattr(openai_client, "async_client"):
            try:
                provider = OpenAIProvider(openai_client=openai_client.async_client)
                model_reference = model_name or getattr(openai_client, "model", None)
                if model_reference is None:
                    raise ValueError("OpenAI model name is not configured")
                model = PydanticOpenAIModel(model_reference, provider=provider)

                model_settings = self._build_model_settings(openai_client)
                agent_kwargs: dict[str, Any] = {}
                if model_settings is not None:
                    agent_kwargs["model_settings"] = model_settings
                retries = getattr(openai_client, "max_retries", None)
                if isinstance(retries, int) and retries > 0:
                    agent_kwargs["retries"] = retries

                self._generation_agent = PydanticAgent(
                    model=model,
                    result_type=TrainingPlanSchema,
                    system_prompt=PLAN_GENERATION_SYSTEM_PROMPT,
                    **agent_kwargs,
                )
                self._adjust_agent = PydanticAgent(
                    model=model,
                    result_type=TrainingPlanSchema,
                    system_prompt=PLAN_ADJUSTMENT_SYSTEM_PROMPT,
                    **agent_kwargs,
                )
                self._model_name = model_reference
            except Exception:  # pragma: no cover - fall back to heuristic mode
                self._generation_agent = None
                self._adjust_agent = None

    @property
    def model_name(self) -> str | None:
        if self._model_name:
            return self._model_name
        if self._openai_client is not None:
            return getattr(self._openai_client, "model", None)
        return None

    def generate_plan(self, context: PlanGenerationContext) -> AgentInvocationResult:
        prompt = self._render_prompt("PLAN_GENERATION_CONTEXT", context)
        return self._invoke_agent(
            agent=self._generation_agent,
            prompt=prompt,
            context=context,
            heuristic=self._heuristic_generate,
        )

    def adjust_plan(self, context: PlanAdjustmentContext) -> AgentInvocationResult:
        prompt = self._render_prompt("PLAN_ADJUSTMENT_CONTEXT", context)
        return self._invoke_agent(
            agent=self._adjust_agent,
            prompt=prompt,
            context=context,
            heuristic=self._heuristic_adjust,
        )

    # --- Internal helpers ---------------------------------------------------
    def _invoke_agent(
        self,
        *,
        agent: PydanticAgent | None,
        prompt: str,
        context: PlanGenerationContext | PlanAdjustmentContext,
        heuristic: Callable[[Any], TrainingPlanSchema],
    ) -> AgentInvocationResult:
        error: str | None = None
        if agent is not None:
            try:
                run_result: AgentRunResult[Any] = agent.run_sync(prompt)
                return self._build_agent_result(prompt, run_result)
            except Exception as exc:  # pragma: no cover - fallback executed
                error = str(exc)

        plan = heuristic(context)
        return AgentInvocationResult(
            plan=plan,
            prompt=prompt,
            messages_json=None,
            usage=None,
            model_name=self.model_name,
            fallback_used=True,
            error=error,
        )

    def _build_agent_result(
        self,
        prompt: str,
        run_result: AgentRunResult[Any],
    ) -> AgentInvocationResult:
        output = run_result.output
        if isinstance(output, TrainingPlanSchema):
            plan_schema = output
        else:
            plan_schema = TrainingPlanSchema.model_validate(output)

        messages_json: str | None = None
        if hasattr(run_result, "new_messages_json"):
            try:
                messages_json = run_result.new_messages_json().decode("utf-8")
            except Exception:  # pragma: no cover - diagnostics only
                messages_json = None

        usage: RunUsage | None = None
        if hasattr(run_result, "usage"):
            try:
                usage = run_result.usage()
            except Exception:  # pragma: no cover - diagnostics only
                usage = None

        return AgentInvocationResult(
            plan=plan_schema,
            prompt=prompt,
            messages_json=messages_json,
            usage=usage,
            model_name=self.model_name,
            fallback_used=False,
        )

    def _build_model_settings(self, openai_client: Any) -> OpenAIModelSettings | None:
        settings_kwargs: dict[str, Any] = {}
        if self._temperature is not None:
            settings_kwargs["temperature"] = self._temperature
        if self._max_output_tokens is not None:
            settings_kwargs["max_tokens"] = self._max_output_tokens
        timeout = getattr(openai_client, "timeout_seconds", None)
        if timeout:
            settings_kwargs["timeout"] = timeout
        if not settings_kwargs:
            return None
        try:
            return OpenAIModelSettings(**settings_kwargs)
        except Exception:  # pragma: no cover - fallback if settings invalid
            return None

    def _render_prompt(
        self,
        label: str,
        context: PlanGenerationContext | PlanAdjustmentContext,
    ) -> str:
        payload = context.model_dump(mode="json")
        serialized = json.dumps(payload, indent=2, default=str)
        return f"{label}:\n{serialized}"

    # --- Heuristic fallbacks -------------------------------------------------
    def _heuristic_generate(self, context: PlanGenerationContext) -> TrainingPlanSchema:
        duration_weeks = int(context.preferences.get("duration_weeks", 8) or 8)
        duration_weeks = max(1, duration_weeks)
        start_date_value = context.preferences.get("start_date") or context.athlete.upcoming_event_date
        if isinstance(start_date_value, str):
            start_date = date.fromisoformat(start_date_value)
        else:
            start_date = start_date_value
        if not start_date:
            start_date = date.today()
        end_date = start_date + timedelta(weeks=duration_weeks)

        workouts = self._heuristic_workouts(start_date, duration_weeks)

        block = TrainingBlockSchema(
            name="Foundation",
            focus="Aerobic Base",
            start_date=start_date,
            end_date=end_date,
            workouts=workouts,
        )

        return TrainingPlanSchema(
            name=f"{context.athlete.primary_sport or 'Multi-sport'} Training Plan",
            goal=context.athlete.goals[0] if context.athlete.goals else context.preferences.get("goal"),
            start_date=start_date,
            end_date=end_date,
            status="draft",
            blocks=[block],
            workouts=workouts,
        )

    def _heuristic_adjust(self, context: PlanAdjustmentContext) -> TrainingPlanSchema:
        plan = context.plan.model_copy(deep=True)
        latest_activity = context.latest_activity
        if latest_activity and latest_activity.streams and latest_activity.streams.power:
            power_summary = latest_activity.streams.power
            if power_summary.intensity_factor and power_summary.intensity_factor > 1.05:
                recovery_day = (plan.end_date or date.today()) + timedelta(days=1)
                recovery_workout = WorkoutSchema(
                    scheduled_date=recovery_day,
                    sport_type=latest_activity.sport_type,
                    name="Recovery Ride",
                    description="Easy spin to absorb training stress",
                    duration_minutes=45,
                    target_intensity="recovery",
                    target_tss=20,
                )
                plan.workouts.append(recovery_workout)
                if plan.blocks:
                    plan.blocks[-1].workouts.append(recovery_workout)
                plan.goal = (plan.goal or "Training") + " (adjusted)"
        return plan

    def _heuristic_workouts(
        self,
        start_date: date,
        duration_weeks: int,
    ) -> list[WorkoutSchema]:
        base_duration = 60
        workouts: list[WorkoutSchema] = []
        for week in range(duration_weeks):
            week_start = start_date + timedelta(weeks=week)
            workouts.append(
                WorkoutSchema(
                    scheduled_date=week_start,
                    sport_type="ride",
                    name="Endurance Ride",
                    description="Steady Z2 ride focusing on aerobic base.",
                    duration_minutes=base_duration + week * 10,
                    target_intensity="endurance",
                    target_tss=60 + week * 5,
                )
            )
            workouts.append(
                WorkoutSchema(
                    scheduled_date=week_start + timedelta(days=2),
                    sport_type="ride",
                    name="Threshold Intervals",
                    description="3x10 min at threshold with 5 min recovery.",
                    duration_minutes=base_duration,
                    target_intensity="threshold",
                    target_tss=75 + week * 5,
                )
            )
        return workouts
