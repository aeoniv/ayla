"""Validate delivery-service (Phase 1) session JWTs. Same HS256 + SESSION_SECRET."""
from __future__ import annotations

import logging
from dataclasses import dataclass

import jwt
from fastapi import Header, HTTPException

from .config import get_settings

logger = logging.getLogger(__name__)


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
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="invalid or expired session")
    except Exception:
        logger.exception("unexpected error decoding session token")
        raise HTTPException(status_code=401, detail="invalid or expired session")
    return SessionUser(
        user_id=payload["sub"],
        telegram_id=int(payload["tg"]),
        role=payload.get("role", "student"),
    )
