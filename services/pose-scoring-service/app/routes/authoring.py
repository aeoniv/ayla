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
from ..gcs import download_to
from ..pose import LANDMARK_SCHEMA, build_checkpoints, extract_landmarks
from ..references import store_reference

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

    if not body.checkpoint_seconds:
        raise HTTPException(400, "at least one checkpoint timestamp is required")

    with tempfile.TemporaryDirectory() as tmp:
        local = os.path.join(tmp, "full.mp4")
        download_to(body.full_video_path, local)
        seq = extract_landmarks(local)

    if seq["frame_count"] == 0:
        raise HTTPException(422, "no pose detected in reference video")

    try:
        checkpoints = build_checkpoints(seq, body.checkpoint_seconds)
    except ValueError as e:
        raise HTTPException(422, str(e))
    for c in checkpoints:
        c["tolerance"] = body.default_tolerance

    blob_path = store_reference(
        body.movement_id, body.style_id, checkpoints,
        source="auto", fps=seq["fps"], frame_count=seq["frame_count"],
        landmark_schema=LANDMARK_SCHEMA,
    )
    return {
        "ok": True,
        "landmarks_path": blob_path,
        "checkpoint_count": len(checkpoints),
    }
