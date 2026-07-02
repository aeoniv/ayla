"""Phase 3 — owner authoring flow.

Owner-only (gated by OWNER_TELEGRAM_ID via require_owner). Uploads videos to
GCS, enforces the teaser ≤12s rule, and for full movements calls the Phase 2
pose-scoring-service /score/authoring to extract checkpoint reference poses.
"""
from __future__ import annotations

import json
import os
import tempfile

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from google.cloud import firestore as fs

from ..config import get_settings
from ..deps import SessionUser, require_owner
from ..firestore import db, doc_exists
from ..gcs import delete as gcs_delete
from ..gcs import upload_file
from ..media import faststart_inplace, video_duration_seconds

router = APIRouter(prefix="/admin", tags=["admin"])

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


async def _save_temp(upload: UploadFile, path: str) -> None:
    with open(path, "wb") as f:
        f.write(await upload.read())


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


def _parse_checkpoints(raw: str | None) -> list[float] | None:
    """Return parsed checkpoints, or None when the caller omitted them (studio flow)."""
    if raw is None or raw.strip() == "":
        return None
    try:
        vals = json.loads(raw)
    except json.JSONDecodeError:
        raise HTTPException(400, "checkpoint_seconds must be a JSON array")
    if not isinstance(vals, list) or not all(isinstance(v, (int, float)) for v in vals):
        raise HTTPException(400, "checkpoint_seconds must be an array of numbers")
    return [float(v) for v in vals] if vals else None


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


@router.post("/movement")
async def create_movement(
    name: str = Form(...),
    style_id: str = Form(...),
    price_stars: int = Form(...),
    checkpoint_seconds: str | None = Form(None),  # JSON array; omit to author via Studio later
    teaser_video: UploadFile = File(...),
    full_video: UploadFile = File(...),
    description: str = Form(""),
    owner: SessionUser = Depends(require_owner),
):
    if not doc_exists("styles", style_id):
        raise HTTPException(400, "unknown style_id")
    checkpoints = _parse_checkpoints(checkpoint_seconds)

    ref = db().collection("movements").document()
    mid = ref.id
    teaser_path = f"movements/{mid}/teaser.mp4"
    full_path = f"movements/{mid}/full.mp4"

    with tempfile.TemporaryDirectory() as tmp:
        lt, lf = os.path.join(tmp, "t.mp4"), os.path.join(tmp, "f.mp4")
        await _save_temp(teaser_video, lt)
        await _save_temp(full_video, lf)
        _check_teaser_duration(lt)
        faststart_inplace(lt)
        faststart_inplace(lf)
        upload_file(teaser_path, lt)
        upload_file(full_path, lf)

    ref.set({
        "style_id": style_id,
        "name": name,
        "description": description.strip(),
        "teaser_video_path": teaser_path,
        "full_video_path": full_path,
        "price_stars": int(price_stars),
        "reference_status": "pending" if checkpoints is None else "auto",
        "created_at": fs.SERVER_TIMESTAMP,
    })

    # Auto-authoring: only when caller supplied checkpoint timestamps.
    # If omitted the owner will author via the Studio and save an audited reference.
    if checkpoints is not None:
        try:
            authored = await _call_authoring(mid, style_id, full_path, checkpoints)
        except HTTPException:
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
async def create_variant(
    movement_id: str = Form(...),
    style_id: str = Form(...),
    avatar_id: str = Form(...),
    price_stars: int = Form(...),
    teaser_video: UploadFile = File(...),
    full_video: UploadFile = File(...),
    owner: SessionUser = Depends(require_owner),
):
    if not doc_exists("movements", movement_id):
        raise HTTPException(400, "unknown movement_id")
    if not doc_exists("styles", style_id):
        raise HTTPException(400, "unknown style_id")
    if not doc_exists("avatars", avatar_id):
        raise HTTPException(400, "unknown avatar_id")

    ref = db().collection("movement_style_variants").document()
    vid = ref.id
    teaser_path = f"variants/{vid}/teaser.mp4"
    full_path = f"variants/{vid}/full.mp4"

    with tempfile.TemporaryDirectory() as tmp:
        lt, lf = os.path.join(tmp, "t.mp4"), os.path.join(tmp, "f.mp4")
        await _save_temp(teaser_video, lt)
        await _save_temp(full_video, lf)
        _check_teaser_duration(lt)
        faststart_inplace(lt)
        faststart_inplace(lf)
        upload_file(teaser_path, lt)
        upload_file(full_path, lf)

    ref.set({
        "movement_id": movement_id,
        "style_id": style_id,
        "avatar_id": avatar_id,
        "teaser_video_path": teaser_path,
        "full_video_path": full_path,
        "price_stars": int(price_stars),
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
