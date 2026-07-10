import os
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

_INSECURE_DEFAULT_SESSION_SECRET = "dev-only-change-me"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    gcp_project_id: str = ""
    firestore_database_id: str = "(default)"
    gcs_bucket: str = ""

    # MUST match delivery-service so we can validate its session JWTs.
    session_secret: str = _INSECURE_DEFAULT_SESSION_SECRET

    # Shared secret for the internal /score/authoring endpoint. Only the
    # Phase 3 authoring flow (delivery-service) knows it; never exposed publicly.
    internal_api_key: str = ""

    # Where reference-landmark blobs are written in the bucket.
    references_prefix: str = "references"

    # Frames to resample every sequence to before comparison.
    compare_frames: int = 64


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    if os.getenv("K_SERVICE") and settings.session_secret == _INSECURE_DEFAULT_SESSION_SECRET:
        raise RuntimeError("SESSION_SECRET must be set to a real secret in deployed environments")
    return settings
