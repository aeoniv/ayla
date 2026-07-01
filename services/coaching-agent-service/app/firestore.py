"""Firestore reads (student history + candidates) and coaching_notes writes.

Stateless: every request reads current state fresh. No per-user process.
"""
from __future__ import annotations

from functools import lru_cache

from google.cloud import firestore

from .config import get_settings


@lru_cache
def db() -> firestore.Client:
    return firestore.Client(project=get_settings().gcp_project_id or None)


def recent_attempts(user_id: str, limit: int) -> list[dict]:
    q = (
        db().collection("attempts")
        .where("user_id", "==", user_id)
        .order_by("timestamp", direction="DESCENDING")
        .limit(limit)
    )
    out = []
    for d in q.stream():
        r = d.to_dict()
        ts = r.get("timestamp")
        out.append({
            "movement_id": r.get("movement_id"),
            "style_id": r.get("style_id"),
            "score": r.get("score"),
            "region": r.get("region"),
            "timestamp": ts.isoformat() if ts else None,
        })
    return out


def watch_progress(user_id: str) -> list[dict]:
    q = db().collection("watch_progress").where("user_id", "==", user_id).stream()
    return [
        {"movement_id": d.to_dict().get("movement_id"),
         "seconds_watched": d.to_dict().get("seconds_watched")}
        for d in q
    ]


def candidate_movements(limit: int) -> list[dict]:
    """A small pool of movements for the model to choose 'next' from."""
    q = (
        db().collection("movements")
        .order_by("created_at", direction="DESCENDING")
        .limit(limit)
    )
    return [
        {"movement_id": d.id, "name": d.to_dict().get("name"),
         "style_id": d.to_dict().get("style_id")}
        for d in q.stream()
    ]


def movement_exists(movement_id: str) -> bool:
    return bool(movement_id) and db().collection("movements").document(movement_id).get().exists


def save_coaching_note(user_id: str, movement_id: str | None, text: str,
                       suggested_next: dict | None) -> str:
    ref = db().collection("coaching_notes").document()
    ref.set({
        "user_id": user_id,
        "movement_id": movement_id,
        "generated_text": text,
        "suggested_next": suggested_next,
        "generated_at": firestore.SERVER_TIMESTAMP,
    })
    return ref.id
