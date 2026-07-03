import math
from datetime import datetime, timezone

from fastapi import APIRouter, Depends

from ..deps import SessionUser, current_user
from ..firestore import (
    db, entitled_movement_set, list_user_entitlements, liked_set, toggle_like,
)
from ..gcs import sign
from ..models import FeedItem

router = APIRouter(tags=["feed"])

# Engagement weights. Purchases are the strongest intent signal, then practice
# attempts, then unique views. Tune these as real usage data comes in.
W_PURCHASE = 8.0
W_ATTEMPT = 3.0
W_LIKE = 2.0
W_VIEW = 1.0
# Recency boost decays by half every RECENCY_HALFLIFE_HOURS so fresh content
# still surfaces before it has accumulated engagement.
RECENCY_HALFLIFE_HOURS = 48.0
RECENCY_WEIGHT = 6.0
# How many recent candidates to score in-process before returning the top slice.
CANDIDATE_WINDOW = 100


def _iso(ts):
    return ts.isoformat() if ts is not None else None


def _recency_boost(created) -> float:
    if created is None:
        return 0.0
    try:
        age_h = (datetime.now(timezone.utc) - created).total_seconds() / 3600.0
    except (TypeError, ValueError):
        return 0.0
    return RECENCY_WEIGHT * math.pow(0.5, max(age_h, 0.0) / RECENCY_HALFLIFE_HOURS)


def _score(d: dict) -> float:
    return (
        W_PURCHASE * float(d.get("purchase_count", 0))
        + W_ATTEMPT * float(d.get("attempt_count", 0))
        + W_LIKE * float(d.get("like_count", 0))
        + W_VIEW * float(d.get("view_count", 0))
        + _recency_boost(d.get("created_at"))
    )


@router.get("/feed", response_model=list[FeedItem])
def feed(limit: int = 20, user: SessionUser = Depends(current_user)):
    """Vertical Reels-style feed of movements, ranked by engagement.

    Score = weighted(purchases, attempts, unique views) + a decaying recency
    boost so fresh content still surfaces before it accrues signal. We pull the
    most recent CANDIDATE_WINDOW movements and rank them in-process; this stays
    cheap at current scale and avoids needing a precomputed score index.
    """
    q = (
        db().collection("movements")
        .order_by("created_at", direction="DESCENDING")
        .limit(CANDIDATE_WINDOW)
    )
    docs = list(q.stream())
    docs.sort(key=lambda doc: _score(doc.to_dict()), reverse=True)
    top = docs[:limit]

    top_ids = [doc.id for doc in top]
    liked = liked_set(user.user_id, top_ids)
    entitled = entitled_movement_set(user.user_id, top_ids)
    items: list[FeedItem] = []
    for doc in top:
        d = doc.to_dict()
        items.append(
            FeedItem(
                movement_id=doc.id,
                name=d.get("name", ""),
                description=d.get("description"),
                style_id=d.get("style_id", ""),
                price_stars=int(d.get("price_stars", 0)),
                teaser_url=sign(d.get("teaser_video_path")),
                created_at=_iso(d.get("created_at")),
                like_count=max(0, int(d.get("like_count", 0))),
                liked=doc.id in liked,
                entitled=doc.id in entitled,
            )
        )
    return items


@router.post("/movement/{movement_id}/like")
def like(movement_id: str, user: SessionUser = Depends(current_user)):
    """Toggle the current user's like on a movement (feeds the ranking)."""
    return toggle_like(user.user_id, movement_id)


@router.get("/me/purchases")
def my_purchases(user: SessionUser = Depends(current_user)):
    """What the current user has unlocked (movements + variants), newest first."""
    ents = list_user_entitlements(user.user_id)
    names = {}
    for e in ents:
        mid = e.get("movement_id")
        if mid and mid not in names:
            snap = db().collection("movements").document(mid).get()
            if snap.exists:
                names[mid] = snap.to_dict().get("name", "")
        e["movement_name"] = names.get(mid)
    return {"count": len(ents), "purchases": ents}
