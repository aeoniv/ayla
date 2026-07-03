"""Cached reference loading + the single reference-payload builder.

The real-time gate (/score/checkpoint) polls every ~350ms per practicing
student; without a cache every poll costs a Firestore read AND a full GCS blob
download. References only change when the owner re-authors, so a short TTL
in-process cache removes almost all of that cost. Saves invalidate the local
cache immediately; other instances converge within TTL_SECONDS.

Reference blobs are versioned: each save writes a NEW blob at
{prefix}/{movement}/{style}/{unix_ms}.json and repoints the Firestore reference
doc. Old versions are kept, so a bad save is a one-field rollback, never data
loss.
"""
from __future__ import annotations

import time

from .config import get_settings
from .firestore import get_reference_doc, save_reference
from .gcs import download_json, upload_json

TTL_SECONDS = 60.0

# (movement_id, style_id) -> (expires_at, doc, blob)
_cache: dict[tuple[str, str], tuple[float, dict | None, dict | None]] = {}


def invalidate(movement_id: str, style_id: str) -> None:
    _cache.pop((movement_id, style_id), None)


def load_reference(movement_id: str, style_id: str) -> tuple[dict | None, dict | None]:
    """Return (reference_doc, landmarks_blob), cached. Either may be None."""
    key = (movement_id, style_id)
    hit = _cache.get(key)
    now = time.monotonic()
    if hit and hit[0] > now:
        return hit[1], hit[2]
    doc = get_reference_doc(movement_id, style_id)
    blob = None
    if doc and doc.get("landmarks_path"):
        blob = download_json(doc["landmarks_path"])
    _cache[key] = (now + TTL_SECONDS, doc, blob)
    return doc, blob


def store_reference(
    movement_id: str,
    style_id: str,
    checkpoints: list[dict],
    *,
    source: str,
    fps: float | None = None,
    frame_count: int | None = None,
    landmark_schema: str = "mediapipe_pose_33",
) -> str:
    """Write a versioned reference blob + Firestore doc. Both authoring paths
    (auto and manual audit) go through here so the stored shape never drifts.

    Each checkpoint dict must carry: index, timestamp_seconds, landmarks,
    tolerance; optionally original_landmarks, audit_score, correction_magnitude,
    marked_seconds. Returns the blob path written.
    """
    s = get_settings()
    blob_path = (
        f"{s.references_prefix}/{movement_id}/{style_id}/{int(time.time() * 1000)}.json"
    )
    payload: dict = {"checkpoints": checkpoints, "source": source}
    if fps is not None:
        payload["fps"] = fps
    upload_json(blob_path, payload)

    meta = {
        "landmark_schema": landmark_schema,
        "checkpoint_count": len(checkpoints),
        "source": source,
    }
    if fps is not None:
        meta["fps"] = fps
    if frame_count is not None:
        meta["frame_count"] = frame_count

    checkpoints_meta = [
        {
            "index": c["index"],
            "timestamp_seconds": c["timestamp_seconds"],
            "tolerance": c["tolerance"],
        }
        for c in checkpoints
    ]
    save_reference(movement_id, style_id, blob_path, meta, checkpoints_meta, source=source)
    invalidate(movement_id, style_id)
    return blob_path
