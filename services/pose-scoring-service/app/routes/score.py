"""Student guided-flow endpoints.

All require a valid Phase 1 session token AND a valid movement entitlement — the
full form is needed to practice, so teaser/preview access is never sufficient.

Real-time inference is on-device: the client extracts the student's MediaPipe
landmarks and sends the vector here; the server does the authoritative pose
comparison against the stored checkpoint. Reference docs + blobs are served
through the in-process cache in ..references — the gate polls every ~350ms, so
this path must not hit Firestore/GCS per call.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..firestore import has_movement_entitlement, write_attempt
from ..pose import NUM_LANDMARKS, sanity_check_pose, validate_pose
from ..references import load_reference, store_reference
from ..session import SessionUser, current_user

router = APIRouter(tags=["score"])

# Tolerance band an author may set per checkpoint (0-100 gate score).
_TOL_MIN, _TOL_MAX, _TOL_DEFAULT = 30.0, 95.0, 75.0


def _require_entitlement(user: SessionUser, movement_id: str):
    # The owner authored the content — the Studio must be able to reopen a
    # saved reference and test-practice it without buying it back.
    if user.role == "owner":
        return
    if not has_movement_entitlement(user.user_id, movement_id):
        raise HTTPException(403, "entitlement required to practice this movement")


def _load(movement_id: str, style_id: str) -> tuple[dict, list[dict]]:
    """Cached (reference_doc, checkpoints) or 404."""
    doc, blob = load_reference(movement_id, style_id)
    if doc is None or blob is None:
        raise HTTPException(404, "no reference for this movement/style")
    return doc, blob.get("checkpoints", [])


# --- practice start: where to pause -----------------------------------------

@router.get("/score/checkpoints/{movement_id}/{style_id}")
def checkpoints_meta(movement_id: str, style_id: str, user: SessionUser = Depends(current_user)):
    """Timestamps + tolerances the client uses to pause the reference video.

    Does NOT return reference landmark poses — matching stays server-side.
    """
    _require_entitlement(user, movement_id)
    doc, _ = _load(movement_id, style_id)
    return {
        "movement_id": movement_id,
        "style_id": style_id,
        "checkpoints": doc.get("checkpoints_meta") or [],
    }


@router.get("/score/reference/{movement_id}/{style_id}")
def reference_poses(movement_id: str, style_id: str, user: SessionUser = Depends(current_user)):
    """Reference checkpoint landmark poses — the target the student mirrors.

    Entitlement-gated (they've paid for this movement). Used by the client to
    draw the avatar's target skeleton (ghost) over the video, and by the Studio
    to reopen a saved reference for re-editing (original_landmarks included so
    the audit trail round-trips).
    """
    _require_entitlement(user, movement_id)
    _, cps = _load(movement_id, style_id)
    return {
        "movement_id": movement_id,
        "style_id": style_id,
        "checkpoints": [
            {
                "index": c.get("index", i),
                "timestamp_seconds": c.get("timestamp_seconds"),
                "tolerance": c.get("tolerance", _TOL_DEFAULT),
                "landmarks": c.get("landmarks", []),
                "original_landmarks": c.get("original_landmarks"),
                "audit_score": c.get("audit_score"),
            }
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
    _, checkpoints = _load(body.movement_id, body.style_id)
    if not (0 <= body.checkpoint_index < len(checkpoints)):
        raise HTTPException(400, "checkpoint_index out of range")

    cp = checkpoints[body.checkpoint_index]
    authored = float(cp.get("tolerance", _TOL_DEFAULT))

    # validate_pose enforces the gate: the user's difficulty slider (override)
    # wins, else the authored per-checkpoint tolerance. It clamps and applies the
    # sub-threshold penalty in one place.
    try:
        return validate_pose(cp["landmarks"], body.landmarks,
                             override=body.threshold, authored=authored)
    except ValueError as e:
        raise HTTPException(422, str(e))


# --- manual authoring: store author-audited reference ------------------------

class AuditedCheckpointIn(BaseModel):
    index: int
    timestamp_seconds: float          # exact frame mediaTime the author audited
    landmarks: list                   # 33 x 4 corrected coords
    original_landmarks: list | None = None
    audit_score: float | None = None
    correction_magnitude: float | None = None
    tolerance: float | None = None    # per-checkpoint gate (30-95), default 75


class AuditedReferenceIn(BaseModel):
    movement_id: str
    style_id: str
    checkpoints: list[AuditedCheckpointIn]


@router.post("/score/authoring-audited")
def save_audited_reference(body: AuditedReferenceIn, user: SessionUser = Depends(current_user)):
    """Persist a hand-audited reference from the timeline studio (owner only).

    Stores the SAME shape as auto-authoring (via references.store_reference), so
    every read path works unchanged. Every pose is re-validated server-side —
    the client's audit score is stored for provenance but never trusted as the
    gate: a reference published to paying students must pass sanity checks HERE.
    """
    if user.role != "owner":
        raise HTTPException(403, "owner only")
    if not body.checkpoints:
        raise HTTPException(400, "no checkpoints submitted")

    for c in body.checkpoints:
        if not isinstance(c.landmarks, list) or len(c.landmarks) != NUM_LANDMARKS:
            raise HTTPException(400, f"checkpoint {c.index}: expected {NUM_LANDMARKS} landmarks")
        check = sanity_check_pose(c.landmarks)
        if not check["ok"]:
            raise HTTPException(
                422,
                f"checkpoint {c.index} failed pose validation: {'; '.join(check['issues'])}",
            )

    ordered = sorted(body.checkpoints, key=lambda c: c.timestamp_seconds)
    checkpoints = [
        {
            "index": i,
            "timestamp_seconds": float(c.timestamp_seconds),
            "landmarks": c.landmarks,
            "original_landmarks": c.original_landmarks,
            "audit_score": c.audit_score,
            "correction_magnitude": c.correction_magnitude,
            "tolerance": max(_TOL_MIN, min(_TOL_MAX, float(c.tolerance or _TOL_DEFAULT))),
        }
        for i, c in enumerate(ordered)
    ]
    store_reference(
        body.movement_id, body.style_id, checkpoints, source="manual-audit"
    )
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
    _, checkpoints = _load(body.movement_id, body.style_id)
    if not checkpoints:
        raise HTTPException(404, "no reference for this movement/style")
    if not body.poses:
        raise HTTPException(400, "no poses submitted")

    scores: list[float] = []
    region_penalty: dict[str, float] = {}
    for p in body.poses:
        if not (0 <= p.index < len(checkpoints)):
            continue
        cp = checkpoints[p.index]
        # The authoritative re-score enforces the same authored per-checkpoint
        # gate the client was held to.
        try:
            r = validate_pose(
                cp["landmarks"], p.landmarks,
                authored=float(cp.get("tolerance", _TOL_DEFAULT)),
            )
        except ValueError:
            continue
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
