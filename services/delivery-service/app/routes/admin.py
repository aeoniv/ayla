"""Phase 3 — owner authoring flow.

Owner-only (gated by OWNER_TELEGRAM_ID via require_owner). Videos are uploaded
by the browser DIRECTLY to GCS via signed PUT URLs (see /admin/upload-url) —
never proxied through this service, which would hit Cloud Run's 32 MiB request
cap. The create endpoints then take the uploaded object paths, enforce the
teaser ≤12s rule, and for auto-authored movements call the Phase 2
pose-scoring-service /score/authoring to extract checkpoint reference poses.
"""
from __future__ import annotations

import os
import tempfile
import uuid

import httpx
from fastapi import APIRouter, Depends, Form, HTTPException
from google.cloud import firestore as fs
from pydantic import BaseModel

from ..config import get_settings
from ..deps import SessionUser, require_owner
from ..firestore import db, doc_exists
from ..gcs import blob_exists
from ..gcs import copy as gcs_copy
from ..gcs import delete as gcs_delete
from ..gcs import download_to, signed_upload_url, upload_file
from ..media import faststart_inplace, video_duration_seconds

router = APIRouter(prefix="/admin", tags=["admin"])

# Client-uploaded videos land here first; create endpoints move them to their
# canonical movements/ or variants/ path. Only objects under this prefix may be
# referenced when creating content.
UPLOAD_PREFIX = "uploads"

TELEGRAM_API = "https://api.telegram.org"


@router.get("/catalog")
def catalog(owner: SessionUser = Depends(require_owner)):
    """Full content tree + per-item performance for the admin page.

    Unlock counts are tallied from the `entitlements` collection (authoritative
    for *what sold*); est_stars multiplies unlocks by the current price, so it's
    an estimate if a price was changed after some sales. Actual withdrawable
    revenue is the Telegram balance in /admin/revenue.
    """
    styles = {d.id: d.to_dict().get("name", "") for d in db().collection("styles").stream()}
    avatars = {d.id: d.to_dict().get("name", "") for d in db().collection("avatars").stream()}

    # Tally paid unlocks per movement / variant.
    mv_unlocks: dict[str, int] = {}
    var_unlocks: dict[str, int] = {}
    for d in db().collection("entitlements").stream():
        e = d.to_dict()
        if e.get("scope") == "movement" and e.get("movement_id"):
            mv_unlocks[e["movement_id"]] = mv_unlocks.get(e["movement_id"], 0) + 1
        elif e.get("scope") == "variant" and e.get("variant_id"):
            var_unlocks[e["variant_id"]] = var_unlocks.get(e["variant_id"], 0) + 1

    # Group variants by movement.
    variants_by_mv: dict[str, list] = {}
    for d in db().collection("movement_style_variants").stream():
        v = d.to_dict()
        price = int(v.get("price_stars", 0))
        unlocks = var_unlocks.get(d.id, 0)
        variants_by_mv.setdefault(v.get("movement_id"), []).append({
            "variant_id": d.id,
            "avatar_name": avatars.get(v.get("avatar_id"), ""),
            "style_name": styles.get(v.get("style_id"), ""),
            "price_stars": price,
            "unlocks": unlocks,
            "est_stars": unlocks * price,
        })

    movements = []
    total_est = 0
    for d in db().collection("movements").order_by(
        "created_at", direction=fs.Query.DESCENDING
    ).stream():
        m = d.to_dict()
        price = int(m.get("price_stars", 0))
        unlocks = mv_unlocks.get(d.id, 0)
        vs = variants_by_mv.get(d.id, [])
        est = unlocks * price + sum(v["est_stars"] for v in vs)
        total_est += est
        movements.append({
            "movement_id": d.id,
            "name": m.get("name", ""),
            "style_name": styles.get(m.get("style_id"), ""),
            "price_stars": price,
            # "pending" means the movement can't be practiced yet — it needs
            # authoring in the Studio before its practice loop can sell itself.
            "reference_status": m.get("reference_status", "pending"),
            "unlocks": unlocks,
            "views": int(m.get("view_count", 0)),
            "attempts": int(m.get("attempt_count", 0)),
            "est_stars": est,
            "variants": vs,
        })

    return {
        "styles": [{"style_id": k, "name": v} for k, v in styles.items()],
        "avatars": [{"avatar_id": k, "name": v} for k, v in avatars.items()],
        "movements": movements,
        "total_est_stars": total_est,
    }


@router.get("/course/{movement_id}/members")
def course_members(movement_id: str, owner: SessionUser = Depends(require_owner)):
    """Everyone who unlocked this course, with their practice progress."""
    ents = (
        db().collection("entitlements")
        .where("scope", "==", "movement")
        .where("movement_id", "==", movement_id)
        .stream()
    )
    user_ids = sorted({e.to_dict().get("user_id") for e in ents if e.to_dict().get("user_id")})
    out = []
    for uid in user_ids:
        u = db().collection("users").document(uid).get()
        ud = u.to_dict() or {}
        attempts = list(
            db().collection("attempts")
            .where("user_id", "==", uid)
            .where("movement_id", "==", movement_id)
            .stream()
        )
        scores = [float(a.to_dict().get("score", 0)) for a in attempts]
        ts = [a.to_dict().get("timestamp") for a in attempts if a.to_dict().get("timestamp")]
        out.append({
            "user_id": uid,
            "telegram_id": ud.get("telegram_id"),
            "role": ud.get("role", "student"),
            "attempts": len(attempts),
            "best_score": round(max(scores), 1) if scores else None,
            "last_practiced": max(ts).isoformat() if ts else None,
        })
    return {"movement_id": movement_id, "members": out}


@router.get("/users")
def users_overview(owner: SessionUser = Depends(require_owner)):
    """Directory of every user with engagement + monetization aggregates.

    One stream per collection (users/entitlements/attempts/referral_earnings),
    joined in memory — fine at this scale, revisit past ~10k users.
    """
    ents_by_user: dict[str, int] = {}
    skips_by_user: dict[str, int] = {}
    for d in db().collection("entitlements").stream():
        e = d.to_dict()
        uid = e.get("user_id")
        if not uid:
            continue
        if e.get("scope") == "skip_guidance":
            skips_by_user[uid] = skips_by_user.get(uid, 0) + 1
        else:
            ents_by_user[uid] = ents_by_user.get(uid, 0) + 1

    att_count: dict[str, int] = {}
    att_best: dict[str, float] = {}
    att_last: dict[str, object] = {}
    for d in db().collection("attempts").stream():
        e = d.to_dict()
        uid = e.get("user_id")
        if not uid:
            continue
        att_count[uid] = att_count.get(uid, 0) + 1
        sc = float(e.get("score", 0))
        if sc > att_best.get(uid, -1):
            att_best[uid] = sc
        ts = e.get("timestamp")
        if ts is not None and (uid not in att_last or ts > att_last[uid]):
            att_last[uid] = ts

    ref_earned: dict[str, int] = {}
    for d in db().collection("referral_earnings").stream():
        e = d.to_dict()
        rid = e.get("referrer_id")
        if rid:
            ref_earned[rid] = ref_earned.get(rid, 0) + int(e.get("amount_stars", 0))

    out = []
    for d in db().collection("users").stream():
        u = d.to_dict()
        uid = d.id
        created = u.get("created_at")
        last = att_last.get(uid)
        out.append({
            "user_id": uid,
            "telegram_id": u.get("telegram_id"),
            "role": u.get("role", "student"),
            "referred_by": u.get("referred_by"),
            "joined": created.isoformat() if created else None,
            "unlocks": ents_by_user.get(uid, 0),
            "guidance_skips": skips_by_user.get(uid, 0),
            "attempts": att_count.get(uid, 0),
            "best_score": round(att_best[uid], 1) if uid in att_best else None,
            "last_active": last.isoformat() if last is not None else None,
            "referral_stars": ref_earned.get(uid, 0),
        })
    # Most recently active first, then newest.
    out.sort(key=lambda x: (x["last_active"] or "", x["joined"] or ""), reverse=True)
    return {"count": len(out), "users": out}


@router.get("/user/{user_id}")
def user_detail(user_id: str, owner: SessionUser = Depends(require_owner)):
    """One user's unlocks and per-course practice progress."""
    u = db().collection("users").document(user_id).get()
    if not u.exists:
        raise HTTPException(404, "user not found")
    ud = u.to_dict()

    mv_names = {d.id: d.to_dict().get("name", "") for d in db().collection("movements").stream()}

    unlocks = []
    for d in db().collection("entitlements").where("user_id", "==", user_id).stream():
        e = d.to_dict()
        g = e.get("granted_at")
        unlocks.append({
            "scope": e.get("scope"),
            "movement_id": e.get("movement_id"),
            "movement_name": mv_names.get(e.get("movement_id"), None),
            "variant_id": e.get("variant_id"),
            "granted_at": g.isoformat() if g else None,
        })
    unlocks.sort(key=lambda x: x["granted_at"] or "", reverse=True)

    prog: dict[str, dict] = {}
    for d in db().collection("attempts").where("user_id", "==", user_id).stream():
        e = d.to_dict()
        mid = e.get("movement_id")
        if not mid:
            continue
        p = prog.setdefault(mid, {"movement_id": mid, "movement_name": mv_names.get(mid, mid),
                                  "attempts": 0, "best_score": 0.0, "last": None})
        p["attempts"] += 1
        p["best_score"] = max(p["best_score"], float(e.get("score", 0)))
        ts = e.get("timestamp")
        if ts is not None and (p["last"] is None or ts > p["last"]):
            p["last"] = ts
    progress = []
    for p in prog.values():
        p["best_score"] = round(p["best_score"], 1)
        p["last"] = p["last"].isoformat() if p["last"] is not None else None
        progress.append(p)
    progress.sort(key=lambda x: x["last"] or "", reverse=True)

    created = ud.get("created_at")
    return {
        "user_id": user_id,
        "telegram_id": ud.get("telegram_id"),
        "role": ud.get("role", "student"),
        "referred_by": ud.get("referred_by"),
        "joined": created.isoformat() if created else None,
        "unlocks": unlocks,
        "progress": progress,
    }


@router.get("/revenue")
async def revenue(limit: int = 25, owner: SessionUser = Depends(require_owner)):
    """Owner-only earnings readout, straight from Telegram's Stars ledger.

    Calls the Bot API `getMyStarBalance` (current withdrawable/held balance) and
    `getStarTransactions` (recent history). This is the source of truth for
    revenue — our Firestore `entitlements` only records *what was unlocked*, not
    the money. Returns balance in Stars plus a simplified transaction list.
    """
    s = get_settings()
    if not s.telegram_bot_token:
        raise HTTPException(503, "bot token not configured")
    base = f"{TELEGRAM_API}/bot{s.telegram_bot_token}"

    async with httpx.AsyncClient(timeout=20) as client:
        bal_resp = await client.post(f"{base}/getMyStarBalance", json={})
        tx_resp = await client.post(
            f"{base}/getStarTransactions", json={"offset": 0, "limit": min(limit, 100)}
        )

    balance_stars = None
    bal = bal_resp.json()
    if bal.get("ok"):
        # getMyStarBalance → StarAmount {amount, nanostar_amount}
        balance_stars = bal["result"].get("amount")

    txs = []
    tj = tx_resp.json()
    if tj.get("ok"):
        for t in tj["result"].get("transactions", []):
            # Incoming (a user paid us) has a `source`; outgoing (withdrawal /
            # refund to a user) has a `receiver`.
            incoming = "source" in t
            txs.append({
                "id": t.get("id"),
                "stars": t.get("amount"),
                "direction": "in" if incoming else "out",
                "date": t.get("date"),
            })
    elif not bal.get("ok"):
        # Both calls failed — surface Telegram's error so it's debuggable.
        raise HTTPException(502, f"telegram: {bal.get('description') or tj.get('description')}")

    total_in = sum(t["stars"] for t in txs if t["direction"] == "in")
    return {
        "balance_stars": balance_stars,
        "recent_income_stars": total_in,
        "transaction_count": len(txs),
        "transactions": txs,
        "note": "Withdraw via Fragment (TON). Balance appears after the first real Star payment.",
    }


def _check_teaser_duration(local_path: str) -> float:
    s = get_settings()
    try:
        dur = video_duration_seconds(local_path)
    except ValueError as e:
        raise HTTPException(400, f"invalid teaser video: {e}")
    if dur > s.max_teaser_seconds + 0.2:  # small slack for container rounding
        raise HTTPException(
            400,
            f"teaser is {dur:.1f}s; max is {s.max_teaser_seconds:.0f}s",
        )
    return dur


def _require_upload(path: str, label: str) -> None:
    """Reject anything that isn't a real object the client just uploaded.

    Only objects under UPLOAD_PREFIX are accepted, so a create call can never be
    tricked into referencing (and re-signing) an arbitrary bucket path.
    """
    if not path or not path.startswith(UPLOAD_PREFIX + "/"):
        raise HTTPException(400, f"{label}_path must be an uploaded object under {UPLOAD_PREFIX}/")
    if not blob_exists(path):
        raise HTTPException(400, f"{label} upload not found — did the upload finish?")


def _place_videos(teaser_src: str, full_src: str, teaser_dst: str, full_dst: str) -> None:
    """Move two client-uploaded staging videos to their canonical paths.

    Teaser is downloaded to enforce the ≤12s rule and faststarted (it's tiny).
    The full video is copied SERVER-SIDE (never pulled into this instance) so an
    arbitrarily large reference video can't OOM Cloud Run. Callers roll back the
    canonical objects on any later failure; staging is cleared by the caller.
    """
    with tempfile.TemporaryDirectory() as tmp:
        lt = os.path.join(tmp, "t.mp4")
        download_to(teaser_src, lt)
        _check_teaser_duration(lt)
        faststart_inplace(lt)
        upload_file(teaser_dst, lt)
    gcs_copy(full_src, full_dst)


async def _call_authoring(movement_id: str, style_id: str, full_path: str,
                          checkpoint_seconds: list[float]) -> dict:
    s = get_settings()
    if not s.pose_scoring_url or not s.internal_api_key:
        raise HTTPException(503, "pose-scoring-service not configured")
    url = s.pose_scoring_url.rstrip("/") + "/score/authoring"
    async with httpx.AsyncClient(timeout=300) as client:
        resp = await client.post(
            url,
            headers={"X-Internal-Key": s.internal_api_key},
            json={
                "movement_id": movement_id,
                "style_id": style_id,
                "full_video_path": full_path,
                "checkpoint_seconds": checkpoint_seconds,
            },
        )
    if resp.status_code != 200:
        raise HTTPException(502, f"authoring failed: {resp.status_code} {resp.text}")
    return resp.json()


class UploadUrlRequest(BaseModel):
    kind: str                       # "teaser" | "full"
    content_type: str = "video/mp4"


class CreateMovementRequest(BaseModel):
    name: str
    style_id: str
    price_stars: int
    teaser_path: str                # object path from /admin/upload-url
    full_path: str
    description: str = ""
    checkpoint_seconds: list[float] | None = None  # omit/empty -> author via Studio


class CreateVariantRequest(BaseModel):
    movement_id: str
    style_id: str
    avatar_id: str
    price_stars: int
    teaser_path: str
    full_path: str


@router.post("/upload-url")
def create_upload_url(body: UploadUrlRequest, owner: SessionUser = Depends(require_owner)):
    """Mint a signed PUT URL so the browser uploads a video straight to GCS.

    The browser PUTs the file bytes to `url` (with a `Content-Type` header equal
    to `content_type`), then passes `path` back to /admin/movement or
    /admin/movement-variant. This keeps large videos off the Cloud Run request
    path entirely (its 32 MiB body cap is what made big uploads fail).
    """
    if body.kind not in ("teaser", "full"):
        raise HTTPException(400, "kind must be 'teaser' or 'full'")
    content_type = body.content_type or "video/mp4"
    path = f"{UPLOAD_PREFIX}/{uuid.uuid4().hex}/{body.kind}.mp4"
    return {"path": path, "url": signed_upload_url(path, content_type), "content_type": content_type}


@router.post("/movement")
async def create_movement(body: CreateMovementRequest, owner: SessionUser = Depends(require_owner)):
    if not doc_exists("styles", body.style_id):
        raise HTTPException(400, "unknown style_id")
    _require_upload(body.teaser_path, "teaser")
    _require_upload(body.full_path, "full")
    checkpoints = body.checkpoint_seconds or None  # empty list -> studio flow

    ref = db().collection("movements").document()
    mid = ref.id
    teaser_path = f"movements/{mid}/teaser.mp4"
    full_path = f"movements/{mid}/full.mp4"

    try:
        _place_videos(body.teaser_path, body.full_path, teaser_path, full_path)
    except Exception:
        # Nothing is committed yet — drop any canonical object we may have
        # written before re-raising (gcs_delete is best-effort / no-op if absent).
        gcs_delete(teaser_path)
        gcs_delete(full_path)
        raise
    finally:
        gcs_delete(body.teaser_path)  # staging no longer needed either way
        gcs_delete(body.full_path)

    ref.set({
        "style_id": body.style_id,
        "name": body.name,
        "description": body.description.strip(),
        "teaser_video_path": teaser_path,
        "full_video_path": full_path,
        "price_stars": int(body.price_stars),
        "reference_status": "pending" if checkpoints is None else "auto",
        "created_at": fs.SERVER_TIMESTAMP,
    })

    # Auto-authoring: only when caller supplied checkpoint timestamps.
    # If omitted the owner will author via the Studio and save an audited reference.
    if checkpoints is not None:
        try:
            authored = await _call_authoring(mid, body.style_id, full_path, checkpoints)
        except Exception:
            # Roll back the half-created movement on ANY authoring failure — an
            # HTTPException, but also a timeout / connection reset to
            # pose-scoring (httpx raises those, not HTTPException). Without this
            # the catch missed them and left an orphaned movement in the catalog
            # that can never be practiced.
            ref.delete()
            gcs_delete(teaser_path)
            gcs_delete(full_path)
            raise
        checkpoint_count = authored.get("checkpoint_count")
    else:
        checkpoint_count = 0

    return {"ok": True, "movement_id": mid, "checkpoint_count": checkpoint_count,
            "reference_status": "pending" if checkpoints is None else "auto"}


@router.post("/movement-variant")
async def create_variant(body: CreateVariantRequest, owner: SessionUser = Depends(require_owner)):
    if not doc_exists("movements", body.movement_id):
        raise HTTPException(400, "unknown movement_id")
    if not doc_exists("styles", body.style_id):
        raise HTTPException(400, "unknown style_id")
    if not doc_exists("avatars", body.avatar_id):
        raise HTTPException(400, "unknown avatar_id")
    _require_upload(body.teaser_path, "teaser")
    _require_upload(body.full_path, "full")

    ref = db().collection("movement_style_variants").document()
    vid = ref.id
    teaser_path = f"variants/{vid}/teaser.mp4"
    full_path = f"variants/{vid}/full.mp4"

    try:
        _place_videos(body.teaser_path, body.full_path, teaser_path, full_path)
    except Exception:
        gcs_delete(teaser_path)
        gcs_delete(full_path)
        raise
    finally:
        gcs_delete(body.teaser_path)
        gcs_delete(body.full_path)

    ref.set({
        "movement_id": body.movement_id,
        "style_id": body.style_id,
        "avatar_id": body.avatar_id,
        "teaser_video_path": teaser_path,
        "full_video_path": full_path,
        "price_stars": int(body.price_stars),
        "created_at": fs.SERVER_TIMESTAMP,
    })
    return {"ok": True, "variant_id": vid}


@router.post("/style")
async def create_style(
    name: str = Form(...),
    owner: SessionUser = Depends(require_owner),
):
    """Register a lineage/discipline style (e.g. Taichi, Shaolin, Meihua)."""
    ref = db().collection("styles").document()
    ref.set({"name": name})
    return {"ok": True, "style_id": ref.id}


@router.post("/avatar")
async def create_avatar(
    name: str = Form(...),
    style_id: str = Form(...),
    owner: SessionUser = Depends(require_owner),
):
    if not doc_exists("styles", style_id):
        raise HTTPException(400, "unknown style_id")
    ref = db().collection("avatars").document()
    ref.set({"name": name, "style_id": style_id})
    return {"ok": True, "avatar_id": ref.id}
