"""Firestore access: entitlement checks, reference storage, attempts writes.

Entitlement logic mirrors delivery-service exactly (per-movement OR active
subscription) — scoring requires the full form, so teaser/preview access alone
is never sufficient.
"""
from __future__ import annotations

import time
from functools import lru_cache

from google.cloud import firestore

from .config import get_settings


@lru_cache
def db() -> firestore.Client:
    return firestore.Client(project=get_settings().gcp_project_id or None)


def has_movement_entitlement(user_id: str, movement_id: str) -> bool:
    ent = db().collection("entitlements")
    q = (
        ent.where("user_id", "==", user_id)
        .where("scope", "==", "movement")
        .where("movement_id", "==", movement_id)
        .limit(1)
    )
    if list(q.stream()):
        return True
    # active subscription
    now = time.time()
    for d in ent.where("user_id", "==", user_id).where("scope", "==", "subscription").stream():
        exp = d.to_dict().get("subscription_expires_at")
        if exp is None or exp.timestamp() > now:
            return True
    return False


def reference_ref(movement_id: str, style_id: str):
    """Per-(movement, style) reference doc — see README design note."""
    return (
        db().collection("movements").document(movement_id)
        .collection("references").document(style_id)
    )


def save_reference(
    movement_id: str, style_id: str, blob_path: str, meta: dict, checkpoints_meta: list
) -> None:
    """Store the reference doc (no landmark arrays — those live in the blob).

    checkpoints_meta: [{index, timestamp_seconds, tolerance}] for the client to
    drive playback; full landmark data is in the GCS blob at blob_path.
    """
    reference_ref(movement_id, style_id).set(
        {
            "movement_id": movement_id,
            "style_id": style_id,
            "landmarks_path": blob_path,
            "meta": meta,
            "checkpoints_meta": checkpoints_meta,
            "extracted_at": firestore.SERVER_TIMESTAMP,
        }
    )
    # Mirror the path onto the movement doc for the movement's home style, to
    # match docs/data-model.md's reference_landmarks_path field.
    mv = db().collection("movements").document(movement_id)
    snap = mv.get()
    if snap.exists and snap.to_dict().get("style_id") == style_id:
        mv.update({"reference_landmarks_path": blob_path, "reference_landmarks_meta": meta})


def get_reference_path(movement_id: str, style_id: str) -> str | None:
    snap = reference_ref(movement_id, style_id).get()
    return snap.to_dict().get("landmarks_path") if snap.exists else None


def get_checkpoints_meta(movement_id: str, style_id: str) -> list | None:
    """Client-facing checkpoint metadata (index, timestamp, tolerance). No poses."""
    snap = reference_ref(movement_id, style_id).get()
    return snap.to_dict().get("checkpoints_meta") if snap.exists else None


def write_attempt(user_id: str, movement_id: str, style_id: str, score: float, region: str) -> str:
    ref = db().collection("attempts").document()
    ref.set(
        {
            "user_id": user_id,
            "movement_id": movement_id,
            "style_id": style_id,
            "score": score,
            "region": region,
            "timestamp": firestore.SERVER_TIMESTAMP,
        }
    )
    return ref.id
