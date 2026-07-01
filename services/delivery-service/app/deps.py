"""FastAPI dependencies: session auth + owner gate."""
from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException

from .auth import decode_session_token
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
        payload = decode_session_token(token)
    except Exception:
        raise HTTPException(status_code=401, detail="invalid or expired session")
    return SessionUser(
        user_id=payload["sub"],
        telegram_id=int(payload["tg"]),
        role=payload.get("role", "student"),
    )


def require_owner(user: SessionUser = Depends(current_user)) -> SessionUser:
    if user.role != "owner" or user.telegram_id != get_settings().owner_telegram_id:
        raise HTTPException(status_code=403, detail="owner only")
    return user
