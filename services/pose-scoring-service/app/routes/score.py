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

from ..config import get_settings
from ..firestore import (
    get_checkpoints_meta,
    get_reference_path,
    has_movement_entitlement,
    save_reference,
    write_attempt,
)
from ..gcs import download_json, upload_json
from ..pose import LANDMARK_SCHEMA, NUM_LANDMARKS, validate_pose
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


@router.get("/score/reference/{movement_id}/{style_id}")
def reference_poses(movement_id: str, style_id: str, user: SessionUser = Depends(current_user)):
    """Reference checkpoint landmark poses — the target the student mirrors.

    Entitlement-gated (they've paid for this movement). Used by the client to
    draw the avatar's target skeleton (ghost) over the video and for debugging
    the overlay independent of the camera.
    """
    _require_entitlement(user, movement_id)
    cps = _load_checkpoints(movement_id, style_id)
    return {
        "movement_id": movement_id,
        "style_id": style_id,
        "checkpoints": [
            {"index": c.get("index", i), "landmarks": c.get("landmarks", [])}
            for i, c in enumerate(cps)
        ],
    }


# --- real-time gate ---------------------------------------------------------

class CheckpointMatch(BaseModel):
    movement_id: str
    style_id: str
    checkpoint_index: int
    landmarks: list  # 33 x 4 (x,y,z,visibility)
    threshold: float | None = None  # user difficulty override (easy→hard)


@router.post("/score/checkpoint")
def score_checkpoint(body: CheckpointMatch, user: SessionUser = Depends(current_user)):
    """Gate one checkpoint. On matched=true the client resumes playback."""
    _require_entitlement(user, body.movement_id)
    checkpoints = _load_checkpoints(body.movement_id, body.style_id)
    if not (0 <= body.checkpoint_index < len(checkpoints)):
        raise HTTPException(400, "checkpoint_index out of range")

    authored = 75.0
    meta = get_checkpoints_meta(body.movement_id, body.style_id) or []
    for m in meta:
        if m.get("index") == body.checkpoint_index:
            authored = float(m.get("tolerance", 75.0))
            break

    # validate_pose enforces the gate: the user's difficulty slider (override)
    # wins, else the authored per-checkpoint tolerance. It clamps and applies the
    # sub-threshold penalty in one place.
    ref_pose = checkpoints[body.checkpoint_index]["landmarks"]
    return validate_pose(ref_pose, body.landmarks, override=body.threshold, authored=authored)


# --- manual authoring: store author-audited reference ------------------------

class AuditedCheckpointIn(BaseModel):
    index: int
    timestamp_seconds: float          # exact frame mediaTime the author audited
    landmarks: list                   # 33 x 4 corrected coords
    original_landmarks: list | None = None
    audit_score: float | None = None
    correction_magnitude: float | None = None


class AuditedReferenceIn(BaseModel):
    movement_id: str
    style_id: str
    checkpoints: list[AuditedCheckpointIn]


@router.post("/score/authoring-audited")
def save_audited_reference(body: AuditedReferenceIn, user: SessionUser = Depends(current_user)):
    """Persist a hand-audited reference from the timeline studio (owner only).

    Stores the SAME shape as auto-authoring, so every read path
    (get_checkpoints_meta / reference blob / matching) works unchanged. Because
    the client sends the exact landmarks it corrected for the exact frame it
    timestamped, this reference carries none of the frame-drift or mis-detection
    error of the auto path.
    """
    if user.role != "owner":
        raise HTTPException(403, "owner only")
    if not body.checkpoints:
        raise HTTPException(400, "no checkpoints submitted")
    for c in body.checkpoints:
        if not isinstance(c.landmarks, list) or len(c.landmarks) != NUM_LANDMARKS:
            raise HTTPException(400, f"checkpoint {c.index}: expected {NUM_LANDMARKS} landmarks")

    s = get_settings()
    ordered = sorted(body.checkpoints, key=lambda c: c.timestamp_seconds)
    checkpoints = [
        {
            "index": i,
            "timestamp_seconds": float(c.timestamp_seconds),
            "landmarks": c.landmarks,
            "audit_score": c.audit_score,
            "correction_magnitude": c.correction_magnitude,
        }
        for i, c in enumerate(ordered)
    ]
    blob_path = f"{s.references_prefix}/{body.movement_id}/{body.style_id}.json"
    upload_json(blob_path, {"checkpoints": checkpoints, "source": "manual-audit"})

    meta = {
        "landmark_schema": LANDMARK_SCHEMA,
        "checkpoint_count": len(checkpoints),
        "source": "manual-audit",
    }
    checkpoints_meta = [
        {"index": c["index"], "timestamp_seconds": c["timestamp_seconds"], "tolerance": 75.0}
        for c in checkpoints
    ]
    save_reference(body.movement_id, body.style_id, blob_path, meta, checkpoints_meta)
    return {"ok": True, "checkpoint_count": len(checkpoints)}


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

    # Authored tolerance per checkpoint index (default 75) so the authoritative
    # re-score enforces the same gate the client was held to.
    meta = get_checkpoints_meta(body.movement_id, body.style_id) or []
    tol_by_index = {m.get("index"): float(m.get("tolerance", 75.0)) for m in meta}

    scores: list[float] = []
    region_penalty: dict[str, float] = {}
    for p in body.poses:
        if not (0 <= p.index < len(checkpoints)):
            continue
        r = validate_pose(
            checkpoints[p.index]["landmarks"], p.landmarks,
            authored=tol_by_index.get(p.index, 75.0),
        )
        # Aggregate the penalized effective score: checkpoints that missed the
        # gate drag the run down instead of counting as-is.
        scores.append(r["effective_score"])
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
