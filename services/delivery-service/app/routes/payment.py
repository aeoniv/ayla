import httpx
from fastapi import APIRouter, Depends, HTTPException

from ..config import get_settings
from ..deps import SessionUser, current_user
from ..firestore import db
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
            {"scope": "variant", "variant_id": body.variant_id,
             "movement_id": d.get("movement_id")},
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

    import json

    req = {
        "title": title[:32],
        "description": description[:255],
        "payload": json.dumps(payload),
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
async def payment_webhook():
    """Telegram successful_payment + Stars subscription renewal handler.

    ┌──────────────────────────────────────────────────────────────────┐
    │  STOP — checkpoint per the build order.                           │
    │  Entitlement schema is confirmed (scope: movement | variant), but │
    │  this endpoint is the designated point to get the owner's final   │
    │  go-ahead before writing the grant/idempotency logic.             │
    │                                                                    │
    │  Planned behavior (NOT yet implemented):                          │
    │   - verify update authenticity (secret_token header)              │
    │   - read successful_payment.telegram_payment_charge_id            │
    │   - idempotent upsert on charge id -> entitlements                 │
    │   - parse invoice_payload -> {scope, movement_id|variant_id,      │
    │     user_id}                                                       │
    │   - Stars subscription renewals -> extend subscription_expires_at │
    └──────────────────────────────────────────────────────────────────┘
    """
    raise HTTPException(
        status_code=501,
        detail="payment webhook not implemented — awaiting owner go-ahead (Phase 1 checkpoint)",
    )
