"""Signed GCS URL generation for video paths.

Only paths inside the one configured bucket are ever signed. The bucket is
empty until content is uploaded via the Phase 3 authoring flow.
"""
from __future__ import annotations

import logging
from datetime import timedelta
from functools import lru_cache

from google.auth import default as google_auth_default
from google.auth.transport.requests import Request
from google.cloud import storage

from .config import get_settings

logger = logging.getLogger(__name__)

_creds = None


@lru_cache
def _client() -> storage.Client:
    return storage.Client(project=get_settings().gcp_project_id or None)


def _signing_kwargs() -> dict:
    """Keyless V4 signing on Cloud Run via IAM signBlob.

    When SIGNER_SERVICE_ACCOUNT is set, sign using the runtime SA's IAM
    credentials (it holds tokenCreator on itself). Empty => sign directly with
    local ADC/key (dev).
    """
    s = get_settings()
    if not s.signer_service_account:
        return {}
    global _creds
    if _creds is None:
        _creds, _ = google_auth_default()
    if not _creds.valid:
        _creds.refresh(Request())
    return {
        "service_account_email": s.signer_service_account,
        "access_token": _creds.token,
    }


def upload_file(path: str, local_path: str, content_type: str = "video/mp4") -> None:
    """Upload a local file to a bucket-relative object path (Phase 3 authoring)."""
    s = get_settings()
    _client().bucket(s.gcs_bucket).blob(path).upload_from_filename(
        local_path, content_type=content_type
    )


def delete(path: str) -> None:
    """Best-effort delete used to roll back a failed authoring upload."""
    try:
        _client().bucket(get_settings().gcs_bucket).blob(path).delete()
    except Exception:
        logger.exception("failed to delete gcs object during rollback: %s", path)


def sign(path: str | None) -> str | None:
    """Return a time-limited signed GET URL for a bucket-relative object path."""
    if not path:
        return None
    s = get_settings()
    blob = _client().bucket(s.gcs_bucket).blob(path)
    return blob.generate_signed_url(
        version="v4",
        expiration=timedelta(seconds=s.signed_url_ttl_seconds),
        method="GET",
        **_signing_kwargs(),
    )
