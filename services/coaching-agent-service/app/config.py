from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    gcp_project_id: str = ""

    # Must match delivery-service so we can validate its session JWTs.
    session_secret: str = "dev-only-change-me"

    # Owner chose Gemini 3.1 Flash-Lite (not Anthropic) for coaching.
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.1-flash-lite"
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta"

    # How many recent attempts to read as context.
    attempts_window: int = 10
    # Candidate movements to offer the model to pick "next" from.
    candidate_limit: int = 15


@lru_cache
def get_settings() -> Settings:
    return Settings()
