# Ayla — delivery-service (Phase 1)

Cloud Run service: Telegram auth, feed, variant carousel, server-side watch
enforcement, and Stars invoice creation.

## Why Python / FastAPI
- **Phase 2 (pose-scoring) is MediaPipe** — Python-only. Sharing one language
  and dependency toolchain across the two backend services keeps auth/session
  helpers and Firestore models reusable.
- FastAPI gives async HTTP (needed for the Telegram Bot API calls) and typed
  request/response models with almost no boilerplate.

## Endpoints
| method | path | notes |
|--------|------|-------|
| POST | `/auth/telegram` | HMAC-SHA256 initData validation → JWT session token |
| GET  | `/feed` | movements, teaser signed URLs, newest-first (v1 ranking) |
| GET  | `/movement/{id}/variants` | carousel; un-entitled variants blurred, no URL |
| POST | `/playback/progress` | server-authoritative 12s enforcement |
| POST | `/payment/create-invoice` | Telegram Stars (XTR) invoice link |
| POST | `/payment/webhook` | successful_payment + Stars renewals; secret-verified, idempotent |
| POST | `/admin/movement` | **owner-only**: upload teaser(≤12s)+full, author checkpoints, publish |
| POST | `/admin/movement-variant` | **owner-only**: upload variant pair, link via `movement_style_variants` |
| POST | `/admin/avatar` | **owner-only**: register an avatar under a style |
| GET  | `/healthz` | liveness |

## Phase 3 — owner authoring flow
Owner-only (gated by `require_owner`: session role `owner` AND telegram id ==
`OWNER_TELEGRAM_ID`). `/admin/movement`:
1. validates `style_id`, parses `checkpoint_seconds` (JSON array);
2. saves uploads to temp, **rejects the teaser if it exceeds
   `MAX_TEASER_SECONDS` (12s)** via ffprobe — before any GCS write;
3. uploads teaser+full to `movements/{id}/…`, creates the movement doc;
4. calls pose-scoring `/score/authoring` (with `INTERNAL_API_KEY`) to extract
   checkpoint reference poses; **rolls back the doc + blobs if authoring fails**.

Needs `POSE_SCORING_URL` + `INTERNAL_API_KEY`, and the runtime SA now also needs
**object create/delete** on the one bucket (authoring writes videos), in
addition to the read/sign scope from Phase 1.

> Variant scoring: `/admin/movement-variant` uploads/links only (per spec) — it
> does **not** author its own checkpoint references. Practice scores against the
> movement's home-style reference. Add per-variant authoring later if variants
> need independent scoring.

## The three rules that are never skipped
1. **12s free preview on the MAIN video only.** Cumulative seconds are keyed on
   `movement_id` in `watch_progress`, updated monotonically in a Firestore
   transaction (`record_watched_seconds`) — a lower reported value is ignored and
   forward jumps are clamped, so switching style variants can't reset the cap.
2. **Variants get zero free seconds.** `/movement/{id}/variants` only signs a
   playable URL when the user owns that variant; otherwise `blurred/locked`.
   `/playback/progress` for a variant returns `locked` immediately unless entitled.
3. **Entitlement is per movement (main) OR per variant** (`has_movement_entitlement`
   / `has_variant_entitlement`). Same helpers gate Phase 2 scoring.

## Payments — Telegram Stars (XTR) only
`createInvoiceLink` is called with `currency: "XTR"` and an **empty**
`provider_token`. No third-party provider (the connected Smart Glocal Test
provider is fiat and is intentionally unused, per Telegram's digital-goods
policy). The invoice `payload` carries `{scope, movement_id|variant_id, user_id}`
so the (future) webhook can grant idempotently on `telegram_payment_charge_id`.

## Service account (you must create — least privilege)
Scope the Cloud Run runtime SA to exactly:
- `roles/datastore.user` (Firestore read/write)
- `roles/iam.serviceAccountTokenCreator` **on itself** (V4 signed URLs)
- object read on the **one** named bucket only (`roles/storage.objectViewer`
  scoped to `GCS_BUCKET`, or a bucket IAM binding)

Nothing else — no project-wide storage admin, no other buckets.

## Cloud Run V4 signed URLs (implemented)
On Cloud Run the runtime SA has no private key, so `app/gcs.py` signs V4 URLs
via the IAM `signBlob` API: when `SIGNER_SERVICE_ACCOUNT` is set (terraform
injects the runtime SA email and grants it `tokenCreator` on itself), signing
passes `service_account_email` + a refreshed `access_token`. Left empty locally,
it signs directly with ADC/a key file.

## GCS is empty until Phase 3
No videos exist yet. `/feed` and `/variants` return empty lists until the Phase 3
authoring flow uploads content. That is expected, not a bug.

## Run locally
```bash
cp ../../.env.example .env    # fill values; real secrets live in repo-root .env
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8080
```

## What you must configure before it works end to end
- `GCP_PROJECT_ID`, `GCS_BUCKET` (create the bucket)
- `TELEGRAM_BOT_TOKEN` (set), `TELEGRAM_PROVIDER_TOKEN` (leave empty)
- `OWNER_TELEGRAM_ID` (your numeric id)
- `SESSION_SECRET` (a strong random value in prod)
- Deploy to Cloud Run, then register the webhook:
  `setWebhook(url=<service>/payment/webhook, secret_token=<TELEGRAM_WEBHOOK_SECRET>,
  allowed_updates=["message"])`. Set the same `TELEGRAM_WEBHOOK_SECRET` env var so
  the service can verify the `X-Telegram-Bot-Api-Secret-Token` header.

### Entitlement grant (webhook)
- Idempotent: the `entitlements` doc id **is** the `telegram_payment_charge_id`,
  so redelivered updates are no-ops (`granted:false`).
- `invoice_payload` carries `{scope, movement_id|variant_id, user_id}` (bound to
  the buyer at invoice creation), so grants go to the right user.
- Stars subscription renewals: `subscription_expiration_date` → stored as
  `subscription_expires_at`; `_has_active_subscription` treats the furthest-future
  unexpired doc as active.
