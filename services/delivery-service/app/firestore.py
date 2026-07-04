"""Firestore access + entitlement / watch-progress helpers.

These helpers are the single source of truth for the two rules that must never
be silently skipped (see docs/data-model.md):
  - 12s free preview on the MAIN video only; variants get 0 free seconds.
  - entitlement scope is per movement (main video) OR per variant.
"""
from __future__ import annotations

import time
from functools import lru_cache

from google.cloud import firestore

from .config import get_settings


@lru_cache
def db() -> firestore.Client:
    return firestore.Client(project=get_settings().gcp_project_id or None)


# --- users ---------------------------------------------------------------

def upsert_user(telegram_id: int) -> dict:
    """Find or create a user by telegram id. Owner role derived from env."""
    s = get_settings()
    users = db().collection("users")
    hits = list(users.where("telegram_id", "==", telegram_id).limit(1).stream())
    role = "owner" if telegram_id == s.owner_telegram_id else "student"
    if hits:
        doc = hits[0]
        data = doc.to_dict()
        data["id"] = doc.id
        # keep role in sync if owner id changed
        if data.get("role") != role:
            doc.reference.update({"role": role})
            data["role"] = role
        return data

    ref = users.document()
    data = {
        "telegram_id": telegram_id,
        "role": role,
        "created_at": firestore.SERVER_TIMESTAMP,
    }
    ref.set(data)
    data["id"] = ref.id
    return data


# --- entitlements --------------------------------------------------------

def has_movement_entitlement(user_id: str, movement_id: str) -> bool:
    """True if the user owns the MAIN video for this movement (or an active sub)."""
    ent = db().collection("entitlements")
    q = (
        ent.where("user_id", "==", user_id)
        .where("scope", "==", "movement")
        .where("movement_id", "==", movement_id)
        .limit(1)
    )
    if list(q.stream()):
        return True
    return _has_active_subscription(user_id)


def list_user_entitlements(user_id: str) -> list[dict]:
    """All non-subscription purchases for a user, newest first."""
    ent = db().collection("entitlements")
    out: list[dict] = []
    for d in ent.where("user_id", "==", user_id).stream():
        e = d.to_dict()
        granted = e.get("granted_at")
        out.append({
            "scope": e.get("scope"),
            "movement_id": e.get("movement_id"),
            "variant_id": e.get("variant_id"),
            "granted_at": granted.isoformat() if granted is not None else None,
        })
    out.sort(key=lambda x: x["granted_at"] or "", reverse=True)
    return out


def has_variant_entitlement(user_id: str, variant_id: str) -> bool:
    """True if the user owns this specific variant (or an active sub)."""
    ent = db().collection("entitlements")
    q = (
        ent.where("user_id", "==", user_id)
        .where("scope", "==", "variant")
        .where("variant_id", "==", variant_id)
        .limit(1)
    )
    if list(q.stream()):
        return True
    return _has_active_subscription(user_id)


def has_skip_guidance(user_id: str, movement_id: str) -> bool:
    """True if the user paid to skip guided practice for this movement.

    Deliberately NOT covered by subscriptions — it is a per-movement perk.
    """
    ent = db().collection("entitlements")
    q = (
        ent.where("user_id", "==", user_id)
        .where("scope", "==", "skip_guidance")
        .where("movement_id", "==", movement_id)
        .limit(1)
    )
    return bool(list(q.stream()))


def grant_entitlement(
    charge_id: str,
    user_id: str,
    scope: str,
    *,
    movement_id: str | None = None,
    variant_id: str | None = None,
    subscription_tier: str | None = None,
    subscription_expires_at=None,
) -> bool:
    """Idempotently grant an entitlement, keyed on telegram_payment_charge_id.

    The entitlements doc id IS the charge id, so a redelivered webhook is a
    no-op. Returns True if a new grant was written, False if it already existed
    (renewals update the existing subscription doc's expiry).
    """
    ref = db().collection("entitlements").document(charge_id)
    data = {
        "user_id": user_id,
        "scope": scope,
        "movement_id": movement_id,
        "variant_id": variant_id,
        "subscription_tier": subscription_tier,
        "subscription_expires_at": subscription_expires_at,
        "telegram_payment_charge_id": charge_id,
        "granted_at": firestore.SERVER_TIMESTAMP,
    }

    @firestore.transactional
    def _txn(txn) -> bool:
        snap = ref.get(transaction=txn)
        if snap.exists:
            # Subscription renewal for the same charge id: extend expiry only.
            if scope == "subscription" and subscription_expires_at is not None:
                txn.update(ref, {"subscription_expires_at": subscription_expires_at})
            return False
        txn.set(ref, data)
        return True

    created = _txn(db().transaction())
    if created:
        # Purchases are the strongest engagement signal. A variant purchase
        # credits its parent movement.
        mid = movement_id
        if scope == "variant" and variant_id:
            vsnap = db().collection("movement_style_variants").document(variant_id).get()
            mid = vsnap.to_dict().get("movement_id") if vsnap.exists else None
        if mid:
            bump_engagement(mid, "purchase_count")
    return created


def _has_active_subscription(user_id: str) -> bool:
    ent = db().collection("entitlements")
    q = (
        ent.where("user_id", "==", user_id)
        .where("scope", "==", "subscription")
        .stream()
    )
    now = time.time()
    for d in q:
        exp = d.to_dict().get("subscription_expires_at")
        if exp is None:
            return True
        if exp.timestamp() > now:
            return True
    return False


# --- watch progress ------------------------------------------------------

def doc_exists(collection: str, doc_id: str) -> bool:
    return db().collection(collection).document(doc_id).get().exists


def get_watched_seconds(user_id: str, movement_id: str) -> float:
    ref = db().collection("watch_progress").document(f"{user_id}_{movement_id}")
    snap = ref.get()
    return float(snap.to_dict().get("seconds_watched", 0)) if snap.exists else 0.0

def record_watched_seconds(user_id: str, movement_id: str, reported: float) -> float:
    """Monotonic, clamped update. Returns the new cumulative seconds.

    Never trusts a lower number; clamps implausible forward jumps to at most
    the free cap + a small slack so the counter can't be gamed.
    """
    s = get_settings()
    ref = db().collection("watch_progress").document(f"{user_id}_{movement_id}")
    created = {"v": False}

    @firestore.transactional
    def _txn(txn):
        snap = ref.get(transaction=txn)
        created["v"] = not snap.exists
        existing = float(snap.to_dict().get("seconds_watched", 0)) if snap.exists else 0.0
        # allow at most a modest forward step per report to prevent jumping the cap
        max_step = s.free_preview_seconds + 2
        clamped = min(reported, existing + max_step)
        new_val = max(existing, clamped)
        txn.set(
            ref,
            {
                "user_id": user_id,
                "movement_id": movement_id,
                "seconds_watched": new_val,
                "updated_at": firestore.SERVER_TIMESTAMP,
            },
        )
        return new_val

    result = _txn(db().transaction())
    # First view by this user counts once toward the engagement signal.
    if created["v"]:
        bump_engagement(movement_id, "view_count")
    return result


def user_likes(user_id: str, movement_id: str) -> bool:
    return db().collection("likes").document(f"{user_id}_{movement_id}").get().exists


def liked_set(user_id: str, movement_ids: list[str]) -> set[str]:
    """Which of these movements the user has liked — one batched get_all round
    trip instead of a sequential get per movement (this runs on every feed load)."""
    if not movement_ids:
        return set()
    refs = [db().collection("likes").document(f"{user_id}_{mid}") for mid in movement_ids]
    prefix = f"{user_id}_"
    return {
        snap.id[len(prefix):] for snap in db().get_all(refs) if snap.exists
    }


def entitled_movement_set(user_id: str, movement_ids: list[str]) -> set[str]:
    """Which of these movements the user may fully watch/practice.

    One query over the user's movement entitlements (plus the subscription
    check) instead of a per-movement query — the feed calls this for every
    item it returns.
    """
    if not movement_ids:
        return set()
    if _has_active_subscription(user_id):
        return set(movement_ids)
    owned = {
        d.to_dict().get("movement_id")
        for d in db().collection("entitlements")
        .where("user_id", "==", user_id)
        .where("scope", "==", "movement")
        .stream()
    }
    return owned & set(movement_ids)


def toggle_like(user_id: str, movement_id: str) -> dict:
    """Idempotent per-user like toggle. Keeps movement.like_count in sync."""
    ref = db().collection("likes").document(f"{user_id}_{movement_id}")
    if ref.get().exists:
        ref.delete()
        bump_engagement(movement_id, "like_count", -1)
        liked = False
    else:
        ref.set({"user_id": user_id, "movement_id": movement_id,
                 "created_at": firestore.SERVER_TIMESTAMP})
        bump_engagement(movement_id, "like_count", 1)
        liked = True
    snap = db().collection("movements").document(movement_id).get()
    return {"liked": liked, "like_count": max(0, int(snap.to_dict().get("like_count", 0)))}


def bump_engagement(movement_id: str, field: str, n: int = 1) -> None:
    """Increment an engagement counter on a movement doc (best-effort).

    Feeds ranking (see routes/feed.py). Missing fields start at 0. Never raises
    into the caller's happy path — engagement is advisory, not correctness.
    """
    try:
        db().collection("movements").document(movement_id).update(
            {field: firestore.Increment(n)}
        )
    except Exception:
        pass
