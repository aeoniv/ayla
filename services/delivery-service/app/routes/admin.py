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
from ..media import video_duration_seconds

router = APIRouter(prefix="/admin", tags=["admin"])


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


def _parse_checkpoints(raw: str) -> list[float]:
    try:
        vals = json.loads(raw)
    except json.JSONDecodeError:
        raise HTTPException(400, "checkpoint_seconds must be a JSON array")
    if not isinstance(vals, list) or not vals or not all(
        isinstance(v, (int, float)) for v in vals
    ):
        raise HTTPException(400, "checkpoint_seconds must be a non-empty array of numbers")
    return [float(v) for v in vals]


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
    checkpoint_seconds: str = Form(...),  # JSON array of seconds
    teaser_video: UploadFile = File(...),
    full_video: UploadFile = File(...),
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
        _check_teaser_duration(lt)               # reject >12s BEFORE any write
        upload_file(teaser_path, lt)
        upload_file(full_path, lf)

    ref.set({
        "style_id": style_id,
        "name": name,
        "teaser_video_path": teaser_path,
        "full_video_path": full_path,
        "price_stars": int(price_stars),
        "created_at": fs.SERVER_TIMESTAMP,
    })

    # Extract checkpoint references; roll back the publish if it fails.
    try:
        authored = await _call_authoring(mid, style_id, full_path, checkpoints)
    except HTTPException:
        ref.delete()
        gcs_delete(teaser_path)
        gcs_delete(full_path)
        raise

    return {"ok": True, "movement_id": mid, "checkpoint_count": authored.get("checkpoint_count")}


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
