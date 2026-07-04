from urllib.parse import parse_qsl

from fastapi import APIRouter, HTTPException

from ..auth import issue_session_token, validate_init_data
from ..config import get_settings
from ..firestore import upsert_user
from ..models import AuthRequest, AuthResponse

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/telegram", response_model=AuthResponse)
def auth_telegram(body: AuthRequest):
    s = get_settings()
    if not s.telegram_bot_token:
        raise HTTPException(status_code=503, detail="bot token not configured")
    try:
        tg_user = validate_init_data(body.init_data, s.telegram_bot_token)
    except ValueError as e:
        raise HTTPException(status_code=401, detail=f"invalid initData: {e}")

    # Share-referral: t.me/Bot?startapp=ref_<userId> arrives as start_param
    # inside the (already HMAC-validated) initData. Recorded on first auth only.
    sp = dict(parse_qsl(body.init_data, keep_blank_values=True)).get("start_param", "")
    referred_by = sp[4:] if sp.startswith("ref_") and len(sp) > 4 else None

    user = upsert_user(int(tg_user["id"]), referred_by=referred_by)
    token = issue_session_token(user["id"], user["telegram_id"], user["role"])
    return AuthResponse(session_token=token, user_id=user["id"], role=user["role"])
