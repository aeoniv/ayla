"""Student guided-flow endpoints.

All require a valid Phase 1 session token AND a valid movement entitlement — the
full form is needed to practice, so teaser/preview access is never sufficient.

Real-time inference is on-device: the client extracts the student's MediaPipe
landmarks and sends the vector here; the server does the authoritative pose
comparison against the stored checkpoint.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..firestore import (
    get_checkpoints_meta,
    get_reference_path,
    has_movement_entitlement,
    write_attempt,
)
from ..gcs import download_json
from ..pose import compare_pose
from ..session import SessionUser, current_user

router = APIRouter(tags=["score"])


def _require_entitlement(user: SessionUser, movement_id: str):
    if not has_movement_entitlement(user.user_id, movement_id):
        raise HTTPException(403, "entitlement required to practice this movement")


def _load_checkpoints(movement_id: str, style_id: str) -> list[dict]:
    ref_path = get_reference_path(movement_id, style_id)
    if not ref_path:
        raise HTTPException(404, "no reference for this movement/style")
    return download_json(ref_path).get("checkpoints", [])


# --- practice start: where to pause -----------------------------------------

@router.get("/score/checkpoints/{movement_id}/{style_id}")
def checkpoints_meta(movement_id: str, style_id: str, user: SessionUser = Depends(current_user)):
    """Timestamps + tolerances the client uses to pause the reference video.

    Does NOT return reference landmark poses — matching stays server-side.
    """
    _require_entitlement(user, movement_id)
    meta = get_checkpoints_meta(movement_id, style_id)
    if meta is None:
        raise HTTPException(404, "no reference for this movement/style")
    return {"movement_id": movement_id, "style_id": style_id, "checkpoints": meta}


# --- real-time gate ---------------------------------------------------------

class CheckpointMatch(BaseModel):
    movement_id: str
    style_id: str
    checkpoint_index: int
    landmarks: list  # 33 x 4 (x,y,z,visibility)


@router.post("/score/checkpoint")
def score_checkpoint(body: CheckpointMatch, user: SessionUser = Depends(current_user)):
    """Gate one checkpoint. On matched=true the client resumes playback."""
    _require_entitlement(user, body.movement_id)
    checkpoints = _load_checkpoints(body.movement_id, body.style_id)
    if not (0 <= body.checkpoint_index < len(checkpoints)):
        raise HTTPException(400, "checkpoint_index out of range")

    tolerance = 75.0
    meta = get_checkpoints_meta(body.movement_id, body.style_id) or []
    for m in meta:
        if m.get("index") == body.checkpoint_index:
            tolerance = float(m.get("tolerance", 75.0))
            break

    ref_pose = checkpoints[body.checkpoint_index]["landmarks"]
    return compare_pose(ref_pose, body.landmarks, threshold=tolerance)


# --- finalize: authoritative attempt write ----------------------------------

class AttemptPose(BaseModel):
    index: int
    landmarks: list  # 33 x 4


class AttemptSubmit(BaseModel):
    movement_id: str
    style_id: str
    poses: list[AttemptPose]  # the matched pose per checkpoint, in order


@router.post("/score/attempt")
def score_attempt(body: AttemptSubmit, user: SessionUser = Depends(current_user)):
    """Re-score the completed run server-side and write one attempts row."""
    _require_entitlement(user, body.movement_id)
    checkpoints = _load_checkpoints(body.movement_id, body.style_id)
    if not checkpoints:
        raise HTTPException(404, "no reference for this movement/style")
    if not body.poses:
        raise HTTPException(400, "no poses submitted")

    scores: list[float] = []
    region_penalty: dict[str, float] = {}
    for p in body.poses:
        if not (0 <= p.index < len(checkpoints)):
            continue
        r = compare_pose(checkpoints[p.index]["landmarks"], p.landmarks)
        scores.append(r["score"])
        region_penalty[r["worst_region"]] = region_penalty.get(r["worst_region"], 0.0) + (
            100.0 - r["score"]
        )

    if not scores:
        raise HTTPException(400, "no valid checkpoint poses")

    aggregate = round(sum(scores) / len(scores), 1)
    worst_region = max(region_penalty, key=region_penalty.get) if region_penalty else "none"
    attempt_id = write_attempt(
        user.user_id, body.movement_id, body.style_id, aggregate, worst_region
    )
    return {
        "attempt_id": attempt_id,
        "score": aggregate,
        "worst_region": worst_region,
        "checkpoints_scored": len(scores),
    }
