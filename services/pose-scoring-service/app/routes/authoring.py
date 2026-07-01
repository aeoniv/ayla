"""Internal authoring endpoint — extract & store reference landmarks.

Called by the Phase 3 authoring flow (delivery-service) on the FULL video, not
the teaser. NOT publicly exposed: protected by a shared internal API key.
"""
from __future__ import annotations

import os
import tempfile

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from ..config import get_settings
from ..firestore import save_reference
from ..gcs import download_to, upload_json
from ..pose import LANDMARK_SCHEMA, build_checkpoints, extract_landmarks

router = APIRouter(tags=["authoring"])


class AuthoringRequest(BaseModel):
    movement_id: str
    style_id: str
    full_video_path: str  # GCS path to the FULL video
    # Owner-marked checkpoint times (seconds) along the form. Ordered flow.
    checkpoint_seconds: list[float]
    # Optional per-checkpoint match tolerance (0-100 score threshold).
    default_tolerance: float = 75.0


def _check_internal(key: str):
    expected = get_settings().internal_api_key
    if not expected or key != expected:
        raise HTTPException(status_code=403, detail="internal endpoint")


@router.post("/score/authoring")
def score_authoring(body: AuthoringRequest, x_internal_key: str = Header(default="")):
    _check_internal(x_internal_key)
    s = get_settings()

    if not body.checkpoint_seconds:
        raise HTTPException(400, "at least one checkpoint timestamp is required")

    with tempfile.TemporaryDirectory() as tmp:
        local = os.path.join(tmp, "full.mp4")
        download_to(body.full_video_path, local)
        seq = extract_landmarks(local)

    if seq["frame_count"] == 0:
        raise HTTPException(422, "no pose detected in reference video")

    checkpoints = build_checkpoints(seq, body.checkpoint_seconds)

    # GCS blob holds the full landmark data for each checkpoint.
    blob_path = f"{s.references_prefix}/{body.movement_id}/{body.style_id}.json"
    upload_json(blob_path, {"checkpoints": checkpoints, "fps": seq["fps"]})

    meta = {
        "fps": seq["fps"],
        "frame_count": seq["frame_count"],
        "landmark_schema": LANDMARK_SCHEMA,
        "checkpoint_count": len(checkpoints),
    }
    # Small, nested-array-free summary for the client to drive playback.
    checkpoints_meta = [
        {"index": c["index"], "timestamp_seconds": c["timestamp_seconds"],
         "tolerance": body.default_tolerance}
        for c in checkpoints
    ]
    save_reference(body.movement_id, body.style_id, blob_path, meta, checkpoints_meta)
    return {
        "ok": True,
        "landmarks_path": blob_path,
        "checkpoint_count": len(checkpoints),
    }
