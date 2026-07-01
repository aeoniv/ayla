"""Signed GCS URL generation for video paths.

Only paths inside the one configured bucket are ever signed. The bucket is
empty until content is uploaded via the Phase 3 authoring flow.
"""
from __future__ import annotations

from datetime import timedelta
from functools import lru_cache

from google.cloud import storage

from .config import get_settings


@lru_cache
def _client() -> storage.Client:
    return storage.Client(project=get_settings().gcp_project_id or None)


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
        pass


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
    )
