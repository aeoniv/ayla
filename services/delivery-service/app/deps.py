"""FastAPI dependencies: session auth + owner gate."""
from __future__ import annotations

import logging
from dataclasses import dataclass

import jwt
from fastapi import Depends, Header, HTTPException

from .auth import decode_session_token
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
        payload = decode_session_token(token)
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


def is_owner(user: SessionUser) -> bool:
    """Non-raising owner check for entitlement bypasses.

    The owner authored every movement, so they may fully watch/practice their
    own content without a purchase entitlement — the same bypass pose-scoring-
    service applies in _require_entitlement. The role claim is derived server-
    side from owner_telegram_id at auth time, so it's authoritative here.
    """
    return user.role == "owner"


def require_owner(user: SessionUser = Depends(current_user)) -> SessionUser:
    if user.role != "owner" or user.telegram_id != get_settings().owner_telegram_id:
        raise HTTPException(status_code=403, detail="owner only")
    return user
