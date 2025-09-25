from functools import lru_cache
from typing import Literal

from pydantic import AnyHttpUrl, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, case_sensitive=False)

    app_env: Literal["development", "test", "production"] = "development"
    frontend_base_url: AnyHttpUrl
    database_url: str | None = None

    strava_client_id: str
    strava_client_secret: str
    strava_redirect_uri: AnyHttpUrl
    strava_scope: str = "read,activity:read_all"
    strava_authorize_base: AnyHttpUrl = "https://www.strava.com/oauth/authorize"
    strava_token_url: AnyHttpUrl = "https://www.strava.com/oauth/token"

    auth0_domain: str
    auth0_audience: str
    auth0_client_secret: str
    auth0_algorithms: list[str] = Field(default_factory=lambda: ["RS256"])
    auth0_jwks_cache_ttl: int = 3600

    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY")
    openai_model: str = Field(default="gpt-4o-mini")
    openai_temperature: float = Field(default=0.3)
    openai_max_output_tokens: int | None = Field(default=1200)
    openai_request_timeout_seconds: float = Field(default=30.0)
    openai_max_retries: int = Field(default=2)

    task_queue_url: str | None = Field(default=None)
    task_queue_name: str = Field(default="plan-tasks")
    task_queue_job_timeout_seconds: int = Field(default=120)
    task_queue_force_inline: bool = Field(default=False)


@lru_cache
def get_settings() -> Settings:
    return Settings()
