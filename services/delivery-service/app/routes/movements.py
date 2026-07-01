from fastapi import APIRouter, Depends, HTTPException

from ..deps import SessionUser, current_user
from ..firestore import db, has_movement_entitlement, has_variant_entitlement
from ..gcs import sign
from ..models import VariantItem

router = APIRouter(tags=["movements"])


@router.get("/movement/{movement_id}/full")
def full_video(movement_id: str, user: SessionUser = Depends(current_user)):
    """Signed URL for the full reference video — required by the practice flow.

    Entitlement-gated: only a user who owns the movement gets the full form.
    Teaser/preview access is never sufficient (same rule as scoring).
    """
    mv = db().collection("movements").document(movement_id).get()
    if not mv.exists:
        raise HTTPException(status_code=404, detail="movement not found")
    if not has_movement_entitlement(user.user_id, movement_id):
        raise HTTPException(status_code=403, detail="entitlement required")
    d = mv.to_dict()
    return {
        "movement_id": movement_id,
        "style_id": d.get("style_id"),
        "full_url": sign(d.get("full_video_path")),
    }


@router.get("/movement/{movement_id}/variants", response_model=list[VariantItem])
def variants(movement_id: str, user: SessionUser = Depends(current_user)):
    """Horizontal carousel for one movement.

    Each variant is individually purchasable. Un-entitled variants get NO free
    preview: the client shows a blurred poster and a buy prompt. We only sign a
    playable teaser URL for variants the user actually owns.
    """
    mv = db().collection("movements").document(movement_id).get()
    if not mv.exists:
        raise HTTPException(status_code=404, detail="movement not found")

    q = (
        db().collection("movement_style_variants")
        .where("movement_id", "==", movement_id)
        .stream()
    )
    out: list[VariantItem] = []
    for doc in q:
        d = doc.to_dict()
        entitled = has_variant_entitlement(user.user_id, doc.id)
        out.append(
            VariantItem(
                variant_id=doc.id,
                movement_id=movement_id,
                style_id=d.get("style_id", ""),
                avatar_id=d.get("avatar_id", ""),
                price_stars=int(d.get("price_stars", 0)),
                entitled=entitled,
                teaser_url=sign(d.get("teaser_video_path")) if entitled else None,
                locked=not entitled,
                blurred=not entitled,
            )
        )
    return out
