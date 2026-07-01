"""Validate delivery-service (Phase 1) session JWTs.

Same HS256 scheme and SESSION_SECRET as delivery-service. This service never
issues tokens, only verifies them.
"""
from __future__ import annotations

from dataclasses import dataclass

import jwt
from fastapi import Header, HTTPException

from .config import get_settings


@dataclass
class SessionUser:
    user_id: str
    telegram_id: int
    role: str


def current_user(authorization: str = Header(default="")) -> SessionUser:
    if not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    token = authorization.split(" ", 1)[1].strip()
    try:
        payload = jwt.decode(token, get_settings().session_secret, algorithms=["HS256"])
    except Exception:
        raise HTTPException(status_code=401, detail="invalid or expired session")
    return SessionUser(
        user_id=payload["sub"],
        telegram_id=int(payload["tg"]),
        role=payload.get("role", "student"),
    )
