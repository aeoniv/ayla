"""GCS helpers: download videos, read/write landmark JSON blobs."""
from __future__ import annotations

import json
from functools import lru_cache

from google.cloud import storage

from .config import get_settings


@lru_cache
def _client() -> storage.Client:
    return storage.Client(project=get_settings().gcp_project_id or None)


def _bucket():
    return _client().bucket(get_settings().gcs_bucket)


def download_to(path: str, local_path: str) -> None:
    _bucket().blob(path).download_to_filename(local_path)


def upload_json(path: str, obj: dict) -> None:
    _bucket().blob(path).upload_from_string(
        json.dumps(obj), content_type="application/json"
    )


def download_json(path: str) -> dict:
    return json.loads(_bucket().blob(path).download_as_bytes())
