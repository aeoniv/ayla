from __future__ import annotations

from pydantic import BaseModel


class CoachNextRequest(BaseModel):
    # Placeholder for a FUTURE queued avatar-skin generation system. This
    # service does NOT implement any generation behind it — see README.
    requested_custom_skin: str | None = None


class SuggestedNext(BaseModel):
    movement_id: str | None = None
    variant_id: str | None = None


class CoachNextResponse(BaseModel):
    note: str
    suggested_next: SuggestedNext
    coaching_note_id: str
    # Echoed back, unused for now (no generation triggered).
    requested_custom_skin: str | None = None
