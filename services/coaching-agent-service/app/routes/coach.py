"""POST /coach/next — stateless per-request coaching.

Reads the caller's own attempts + watch_progress, makes ONE Gemini call, stores
the result in coaching_notes, and returns it. The user id is taken from the
session token (never trusted from the body) so a caller can only coach itself.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ..config import get_settings
from ..firestore import (
    candidate_movements,
    movement_exists,
    recent_attempts,
    save_coaching_note,
    watch_progress,
)
from ..gemini import generate_coaching
from ..models import CoachNextRequest, CoachNextResponse, SuggestedNext
from ..session import SessionUser, current_user

router = APIRouter(tags=["coach"])


@router.post("/coach/next", response_model=CoachNextResponse)
def coach_next(body: CoachNextRequest, user: SessionUser = Depends(current_user)):
    s = get_settings()
    attempts = recent_attempts(user.user_id, s.attempts_window)
    progress = watch_progress(user.user_id)
    candidates = candidate_movements(s.candidate_limit)

    try:
        result = generate_coaching(attempts, progress, candidates)
    except RuntimeError as e:
        raise HTTPException(502, f"coaching generation failed: {e}")

    # Ground the suggestion: only accept a movement id that actually exists and
    # was among the candidates; otherwise drop it rather than hallucinate.
    candidate_ids = {c["movement_id"] for c in candidates}
    suggested_movement = result["suggested_movement_id"]
    if suggested_movement not in candidate_ids or not movement_exists(suggested_movement):
        suggested_movement = None

    suggested = SuggestedNext(
        movement_id=suggested_movement,
        variant_id=result["suggested_variant_id"] if suggested_movement else None,
    )

    # The note references the student's most recent attempt movement.
    note_movement = attempts[0]["movement_id"] if attempts else suggested_movement
    suggested_dict = suggested.model_dump() if (suggested.movement_id or suggested.variant_id) else None
    note_id = save_coaching_note(user.user_id, note_movement, result["note"], suggested_dict)

    return CoachNextResponse(
        note=result["note"],
        suggested_next=suggested,
        coaching_note_id=note_id,
        requested_custom_skin=body.requested_custom_skin,
    )
