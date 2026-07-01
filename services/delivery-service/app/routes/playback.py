from fastapi import APIRouter, Depends

from ..config import get_settings
from ..deps import SessionUser, current_user
from ..firestore import (
    get_watched_seconds,
    has_movement_entitlement,
    has_variant_entitlement,
    record_watched_seconds,
)
from ..models import ProgressRequest, ProgressResponse

router = APIRouter(tags=["playback"])


@router.post("/playback/progress", response_model=ProgressResponse)
def progress(body: ProgressRequest, user: SessionUser = Depends(current_user)):
    """Server-authoritative watch enforcement.

    Rules (never skipped, see docs/data-model.md):
      - MAIN video: free preview up to free_preview_seconds; the cumulative
        counter is keyed on movement_id so switching variants can't reset it.
      - VARIANT: no free preview at all — locked immediately unless entitled.
    """
    s = get_settings()

    # Variant playback: entitlement-only, zero free seconds.
    if body.variant_id:
        entitled = has_variant_entitlement(user.user_id, body.variant_id)
        watched = get_watched_seconds(user.user_id, body.movement_id)
        return ProgressResponse(
            seconds_watched=watched,
            locked=not entitled,
            free_preview_seconds=0,
        )

    # Main video: entitled users are never capped.
    if has_movement_entitlement(user.user_id, body.movement_id):
        watched = record_watched_seconds(user.user_id, body.movement_id, body.seconds)
        return ProgressResponse(
            seconds_watched=watched,
            locked=False,
            free_preview_seconds=s.free_preview_seconds,
        )

    watched = record_watched_seconds(user.user_id, body.movement_id, body.seconds)
    return ProgressResponse(
        seconds_watched=watched,
        locked=watched >= s.free_preview_seconds,
        free_preview_seconds=s.free_preview_seconds,
    )
