from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime config, loaded from environment (.env in dev)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Telegram
    telegram_bot_token: str = ""
    telegram_bot_username: str = "Ayla_Bot"
    # Stars (XTR) only — provider token stays empty. Never set a fiat provider
    # token here for digital goods.
    telegram_provider_token: str = ""
    owner_telegram_id: int = 0

    # GCP
    gcp_project_id: str = ""
    gcs_bucket: str = ""
    # How long signed video URLs stay valid (seconds).
    signed_url_ttl_seconds: int = 3600

    # Session tokens
    session_secret: str = "dev-only-change-me"
    session_ttl_seconds: int = 60 * 60 * 24 * 7  # 7 days

    # Free preview cap on the MAIN video, in seconds (variants get 0).
    free_preview_seconds: int = 12


@lru_cache
def get_settings() -> Settings:
    return Settings()
