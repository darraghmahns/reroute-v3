"""Simple OpenAI client wrapper used by the plan agent."""

from __future__ import annotations

from typing import Any

from openai import AsyncOpenAI, OpenAI

from app.core.config import Settings


class OpenAIClient:
    def __init__(self, settings: Settings) -> None:
        if not settings.openai_api_key:
            raise ValueError("OPENAI_API_KEY is not configured")
        client_kwargs = {
            "api_key": settings.openai_api_key,
            "timeout": settings.openai_request_timeout_seconds,
            "max_retries": settings.openai_max_retries,
        }
        self._client = OpenAI(**client_kwargs)
        self._async_client = AsyncOpenAI(**client_kwargs)
        self._model = settings.openai_model
        self._temperature = settings.openai_temperature
        self._max_output_tokens = settings.openai_max_output_tokens
        self._timeout_seconds = settings.openai_request_timeout_seconds
        self._max_retries = settings.openai_max_retries

    @property
    def model(self) -> str:
        return self._model

    @property
    def temperature(self) -> float:
        return self._temperature

    @property
    def max_output_tokens(self) -> int | None:
        return self._max_output_tokens

    @property
    def timeout_seconds(self) -> float:
        return self._timeout_seconds

    @property
    def max_retries(self) -> int:
        return self._max_retries

    @property
    def client(self) -> OpenAI:
        return self._client

    @property
    def async_client(self) -> AsyncOpenAI:
        return self._async_client

    def invoke(self, messages: list[dict[str, Any]]) -> dict[str, Any]:
        response = self._client.chat.completions.create(
            model=self._model,
            temperature=self._temperature,
            max_tokens=self._max_output_tokens,
            messages=messages,
            timeout=self._timeout_seconds,
        )
        return response.to_dict()
