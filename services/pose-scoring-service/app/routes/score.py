"""Student scoring endpoint.

Requires a valid Phase 1 session token AND a valid entitlement for the movement
(the full form is needed to score — teaser/preview access is never sufficient).
"""
from __future__ import annotations

import os
import tempfile

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from ..firestore import get_reference_path, has_movement_entitlement, write_attempt
from ..gcs import download_json
from ..pose import compare, extract_landmarks
from ..session import SessionUser, current_user

router = APIRouter(tags=["score"])


@router.post("/score")
async def score(
    movement_id: str = Form(...),
    style_id: str = Form(...),
    video: UploadFile = File(...),
    user: SessionUser = Depends(current_user),
):
    # Entitlement gate — scoring requires the full form.
    if not has_movement_entitlement(user.user_id, movement_id):
        raise HTTPException(403, "entitlement required to score this movement")

    ref_path = get_reference_path(movement_id, style_id)
    if not ref_path:
        raise HTTPException(404, "no reference landmarks for this movement/style")

    reference = download_json(ref_path)

    with tempfile.TemporaryDirectory() as tmp:
        local = os.path.join(tmp, video.filename or "attempt.mp4")
        with open(local, "wb") as f:
            f.write(await video.read())
        attempt_seq = extract_landmarks(local)

    if attempt_seq["frame_count"] == 0:
        raise HTTPException(422, "no pose detected in attempt video")

    result = compare(reference, attempt_seq)
    attempt_id = write_attempt(
        user.user_id, movement_id, style_id, result["score"], result["worst_region"]
    )
    return {"attempt_id": attempt_id, **result}
