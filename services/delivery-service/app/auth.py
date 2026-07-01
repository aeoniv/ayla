"""Telegram Mini App initData validation + session tokens.

initData validation follows Telegram's spec:
  secret_key = HMAC-SHA256(key="WebAppData", msg=bot_token)
  hash       = HMAC-SHA256(key=secret_key, msg=data_check_string)
where data_check_string is every field except `hash`, sorted by key,
joined as `k=v` with newlines.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl

import jwt

from .config import get_settings


def validate_init_data(init_data: str, bot_token: str, max_age_seconds: int = 86400) -> dict:
    """Validate a Telegram WebApp initData string. Returns the parsed user dict.

    Raises ValueError on any failure (bad hash, missing/expired auth_date).
    """
    pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = pairs.pop("hash", None)
    if not received_hash:
        raise ValueError("initData missing hash")

    data_check_string = "\n".join(f"{k}={pairs[k]}" for k in sorted(pairs))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    computed = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(computed, received_hash):
        raise ValueError("initData hash mismatch")

    auth_date = int(pairs.get("auth_date", "0"))
    if auth_date <= 0 or (time.time() - auth_date) > max_age_seconds:
        raise ValueError("initData expired or missing auth_date")

    user_raw = pairs.get("user")
    if not user_raw:
        raise ValueError("initData missing user")
    return json.loads(user_raw)


def issue_session_token(user_id: str, telegram_id: int, role: str) -> str:
    s = get_settings()
    now = int(time.time())
    payload = {
        "sub": user_id,
        "tg": telegram_id,
        "role": role,
        "iat": now,
        "exp": now + s.session_ttl_seconds,
    }
    return jwt.encode(payload, s.session_secret, algorithm="HS256")


def decode_session_token(token: str) -> dict:
    s = get_settings()
    return jwt.decode(token, s.session_secret, algorithms=["HS256"])
