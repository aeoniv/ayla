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
    # Secret set via setWebhook secret_token; echoed by Telegram in the
    # X-Telegram-Bot-Api-Secret-Token header. Verifies webhook authenticity.
    telegram_webhook_secret: str = ""

    # GCP
    gcp_project_id: str = ""
    gcs_bucket: str = ""
    # How long signed video URLs stay valid (seconds).
    signed_url_ttl_seconds: int = 3600
    # On Cloud Run the runtime SA has no private key; V4 signing goes through the
    # IAM signBlob API. Set to the runtime SA email to enable keyless signing.
    # Leave empty locally (ADC/key file signs directly).
    signer_service_account: str = ""

    # Session tokens
    session_secret: str = "dev-only-change-me"
    session_ttl_seconds: int = 60 * 60 * 24 * 7  # 7 days

    # Free preview cap on the MAIN video, in seconds (variants get 0).
    free_preview_seconds: int = 12

    # Max teaser length, seconds. Teasers longer than this are rejected.
    max_teaser_seconds: float = 12.0

    # Phase 3 authoring -> Phase 2 pose-scoring-service (internal call).
    pose_scoring_url: str = ""      # e.g. https://pose-scoring-...run.app
    internal_api_key: str = ""      # shared secret for /score/authoring


@lru_cache
def get_settings() -> Settings:
    return Settings()
