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
from ..pose import LANDMARK_SCHEMA, extract_landmarks

router = APIRouter(tags=["authoring"])


class AuthoringRequest(BaseModel):
    movement_id: str
    style_id: str
    full_video_path: str  # GCS path to the FULL video


def _check_internal(key: str):
    expected = get_settings().internal_api_key
    if not expected or key != expected:
        raise HTTPException(status_code=403, detail="internal endpoint")


@router.post("/score/authoring")
def score_authoring(body: AuthoringRequest, x_internal_key: str = Header(default="")):
    _check_internal(x_internal_key)
    s = get_settings()

    with tempfile.TemporaryDirectory() as tmp:
        local = os.path.join(tmp, "full.mp4")
        download_to(body.full_video_path, local)
        seq = extract_landmarks(local)

    if seq["frame_count"] == 0:
        raise HTTPException(422, "no pose detected in reference video")

    blob_path = f"{s.references_prefix}/{body.movement_id}/{body.style_id}.json"
    upload_json(blob_path, seq)

    meta = {
        "fps": seq["fps"],
        "frame_count": seq["frame_count"],
        "landmark_schema": LANDMARK_SCHEMA,
    }
    save_reference(body.movement_id, body.style_id, blob_path, meta)
    return {"ok": True, "landmarks_path": blob_path, "frame_count": seq["frame_count"]}
