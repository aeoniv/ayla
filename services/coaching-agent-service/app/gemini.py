"""One Gemini 3.1 Flash-Lite call producing the coaching note + next suggestion.

The model is instructed to be encouraging but factual, grounded ONLY in this
student's own history, and NEVER comparative to other students.
"""
from __future__ import annotations

import json
import logging

import httpx

from .config import get_settings

logger = logging.getLogger(__name__)

SYSTEM = (
    "You are Ayla, a movement coach for a Taichi-style practice app. "
    "Write a short (2-3 sentence) note for ONE student. Be encouraging but "
    "factual and specific, referencing their own recent score and the body "
    "region that deviated most. Base everything ONLY on this student's own "
    "history. NEVER compare them to other students or to averages. Then pick "
    "the single best movement for them to try next, choosing ONLY from the "
    "provided candidate list. Respond as strict JSON with keys: "
    "note (string), suggested_movement_id (string from candidates or null), "
    "suggested_variant_id (string or null)."
)


def _build_prompt(attempts: list[dict], progress: list[dict], candidates: list[dict]) -> str:
    return json.dumps({
        "recent_attempts": attempts,
        "watch_progress": progress,
        "candidate_movements": candidates,
    }, ensure_ascii=False)


def generate_coaching(attempts: list[dict], progress: list[dict],
                      candidates: list[dict]) -> dict:
    """Returns {note, suggested_movement_id, suggested_variant_id}.

    Raises RuntimeError on API/parse failure so the caller can surface 502.
    """
    s = get_settings()
    if not s.gemini_api_key:
        raise RuntimeError("GEMINI_API_KEY not configured")

    url = f"{s.gemini_base_url}/models/{s.gemini_model}:generateContent"
    body = {
        "systemInstruction": {"parts": [{"text": SYSTEM}]},
        "contents": [{"role": "user", "parts": [{"text": _build_prompt(attempts, progress, candidates)}]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0.7},
    }
    with httpx.Client(timeout=30) as client:
        resp = client.post(url, headers={"x-goog-api-key": s.gemini_api_key}, json=body)
    if resp.status_code != 200:
        logger.error("gemini error %s: %s", resp.status_code, resp.text)
        raise RuntimeError(f"gemini error {resp.status_code}")

    data = resp.json()
    try:
        text = data["candidates"][0]["content"]["parts"][0]["text"]
        parsed = json.loads(text)
    except (KeyError, IndexError, json.JSONDecodeError) as e:
        raise RuntimeError(f"unparseable gemini response: {e}")

    return {
        "note": str(parsed.get("note", "")).strip(),
        "suggested_movement_id": parsed.get("suggested_movement_id") or None,
        "suggested_variant_id": parsed.get("suggested_variant_id") or None,
    }
