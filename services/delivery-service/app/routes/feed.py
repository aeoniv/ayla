from fastapi import APIRouter, Depends

from ..deps import SessionUser, current_user
from ..firestore import db
from ..gcs import sign
from ..models import FeedItem

router = APIRouter(tags=["feed"])


def _iso(ts):
    return ts.isoformat() if ts is not None else None


@router.get("/feed", response_model=list[FeedItem])
def feed(limit: int = 20, user: SessionUser = Depends(current_user)):
    """Vertical Reels-style feed of movements.

    Ranking (v1): newest first by created_at. This is intentionally simple and
    deterministic; a recommended/personalized ranking is a later improvement
    once we have enough attempts/watch_progress signal (see README).
    """
    q = (
        db().collection("movements")
        .order_by("created_at", direction="DESCENDING")
        .limit(limit)
    )
    items: list[FeedItem] = []
    for doc in q.stream():
        d = doc.to_dict()
        items.append(
            FeedItem(
                movement_id=doc.id,
                name=d.get("name", ""),
                style_id=d.get("style_id", ""),
                price_stars=int(d.get("price_stars", 0)),
                teaser_url=sign(d.get("teaser_video_path")),
                created_at=_iso(d.get("created_at")),
            )
        )
    return items
