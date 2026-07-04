import json
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request

from ..config import get_settings
from ..deps import SessionUser, current_user
from ..firestore import db, grant_entitlement
from ..models import InvoiceRequest, InvoiceResponse

router = APIRouter(prefix="/payment", tags=["payment"])

TELEGRAM_API = "https://api.telegram.org"


def _load_priced_item(body: InvoiceRequest) -> tuple[str, str, int, dict]:
    """Resolve the purchased item -> (title, description, price_stars, payload).

    payload is the createInvoiceLink `payload` we get back verbatim in the
    successful_payment update; it carries what to grant.
    """
    if body.movement_id:
        doc = db().collection("movements").document(body.movement_id).get()
        if not doc.exists:
            raise HTTPException(404, "movement not found")
        d = doc.to_dict()
        return (
            d.get("name", "Movement"),
            "Unlock the full movement video",
            int(d.get("price_stars", 0)),
            {"scope": "movement", "movement_id": body.movement_id},
        )
    if body.variant_id:
        doc = db().collection("movement_style_variants").document(body.variant_id).get()
        if not doc.exists:
            raise HTTPException(404, "variant not found")
        d = doc.to_dict()
        return (
            "Style variant",
            "Unlock this avatar/style variant",
            int(d.get("price_stars", 0)),
            {"scope": "variant", "variant_id": body.variant_id},
        )
    if body.skip_guidance_movement_id:
        mid = body.skip_guidance_movement_id
        doc = db().collection("movements").document(mid).get()
        if not doc.exists:
            raise HTTPException(404, "movement not found")
        d = doc.to_dict()
        # Owner can set skip_guidance_price_stars per movement; default half price.
        price = int(d.get("skip_guidance_price_stars") or max(1, int(d.get("price_stars", 0)) // 2))
        return (
            f"Skip guidance — {d.get('name', 'Movement')}",
            "Watch the full form freely, without guided practice",
            price,
            {"scope": "skip_guidance", "movement_id": mid},
        )
    if body.subscription_tier:
        # Reserved for a future "unlock all" tier; not sold yet.
        raise HTTPException(400, "subscription tier not available yet")
    raise HTTPException(400, "specify movement_id or variant_id")


@router.post("/create-invoice", response_model=InvoiceResponse)
async def create_invoice(body: InvoiceRequest, user: SessionUser = Depends(current_user)):
    """Create a Telegram Stars (XTR) invoice link.

    Stars invoices use an EMPTY provider_token and currency XTR. The amount is
    the star count as a single price component. No third-party provider.
    """
    s = get_settings()
    if not s.telegram_bot_token:
        raise HTTPException(503, "bot token not configured")

    title, description, price_stars, payload = _load_priced_item(body)
    if price_stars <= 0:
        raise HTTPException(400, "item has no valid star price")

    # Bind the payload to the buyer so the webhook grants to the right user.
    payload["user_id"] = user.user_id

    req = {
        "title": title[:32],
        "description": description[:255],
        "payload": json.dumps(payload, separators=(",", ":")),  # ≤128 bytes (Telegram cap)
        "provider_token": "",          # MUST be empty for XTR / Stars
        "currency": "XTR",
        "prices": [{"label": title[:32], "amount": price_stars}],
    }

    url = f"{TELEGRAM_API}/bot{s.telegram_bot_token}/createInvoiceLink"
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(url, json=req)
    data = resp.json()
    if not data.get("ok"):
        raise HTTPException(502, f"telegram createInvoiceLink failed: {data}")
    return InvoiceResponse(invoice_link=data["result"])


@router.post("/webhook")
async def payment_webhook(request: Request):
    """Telegram successful_payment + Stars subscription renewal handler.

    Authenticity: verified via the X-Telegram-Bot-Api-Secret-Token header
    (set through setWebhook's secret_token). Idempotency: entitlements are keyed
    on telegram_payment_charge_id, so a redelivered update is a no-op.
    """
    s = get_settings()

    # 1) Verify the update really came from Telegram.
    if s.telegram_webhook_secret:
        got = request.headers.get("x-telegram-bot-api-secret-token", "")
        if got != s.telegram_webhook_secret:
            raise HTTPException(403, "bad webhook secret")

    update = await request.json()

    # 1b) pre_checkout_query: Telegram REQUIRES an answer within 10s or the
    # payment is cancelled and refunded. Approve it (the invoice was already
    # priced/validated at create-invoice time).
    pcq = update.get("pre_checkout_query")
    if pcq:
        ok = True
        if s.telegram_bot_token:
            url = f"{TELEGRAM_API}/bot{s.telegram_bot_token}/answerPreCheckoutQuery"
            async with httpx.AsyncClient(timeout=10) as client:
                await client.post(url, json={"pre_checkout_query_id": pcq["id"], "ok": ok})
        return {"ok": True, "pre_checkout": True}

    msg = update.get("message") or {}
    sp = msg.get("successful_payment")
    if not sp:
        # Not a payment update (e.g. a plain message we don't act on).
        return {"ok": True, "ignored": True}

    charge_id = sp.get("telegram_payment_charge_id")
    if not charge_id:
        raise HTTPException(400, "missing telegram_payment_charge_id")

    # 2) Recover what was purchased from the invoice payload we set earlier.
    try:
        payload = json.loads(sp.get("invoice_payload", "{}"))
    except json.JSONDecodeError:
        raise HTTPException(400, "unparseable invoice_payload")

    scope = payload.get("scope")
    user_id = payload.get("user_id")
    if not user_id or scope not in ("movement", "variant", "subscription", "skip_guidance"):
        raise HTTPException(400, "invalid invoice_payload")

    # 3) Stars subscriptions: convert expiry (unix seconds) if present.
    expires_at = None
    exp = sp.get("subscription_expiration_date")
    if exp:
        expires_at = datetime.fromtimestamp(int(exp), tz=timezone.utc)

    # 4) Idempotent grant keyed on the charge id.
    created = grant_entitlement(
        charge_id=charge_id,
        user_id=user_id,
        scope=scope,
        movement_id=payload.get("movement_id") if scope in ("movement", "skip_guidance") else None,
        variant_id=payload.get("variant_id") if scope == "variant" else None,
        subscription_tier=payload.get("subscription_tier") if scope == "subscription" else None,
        subscription_expires_at=expires_at,
    )
    return {"ok": True, "granted": created, "charge_id": charge_id}
