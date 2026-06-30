# delivery-service

Stateless Cloud Run HTTP service for the Telegram VoD app. All state lives in
Firestore; the container holds none, so any revision is interchangeable.

## Endpoints

| Method | Path | Status | Notes |
|---|---|---|---|
| `POST` | `/auth/telegram` | **implemented** | Validates `initData` HMAC-SHA256 against the bot token; rejects anything else. |
| `GET`  | `/manifest/:videoId` | wired, **signing stubbed (501)** | Auth via `Authorization: tma <initData>`, Firestore entitlement check, then a 10-min V4 signed URL. |
| `POST` | `/webhook/stars-payment` | **implemented** | Stars `successful_payment`. Authenticated by the webhook secret-token header, idempotent on `telegram_payment_charge_id`, writes the entitlement to Firestore. |
| `GET`  | `/healthz` | implemented | Liveness/readiness for the control-agent. |

## Layout

```
src/
  index.ts            # Express app + route wiring + /healthz
  config.ts           # env-only config (stateless)
  auth/telegram.ts    # initData HMAC validation  (implemented + tested)
  firestore.ts        # entitlement store + final Entitlement schema
  payments/stars.ts   # Stars successful_payment parsing (tested)
  storage.ts          # V4 signed-URL signer      (deferred stub)
  routes/
    auth.ts           # POST /auth/telegram
    manifest.ts       # GET  /manifest/:videoId
    starsWebhook.ts   # POST /webhook/stars-payment  (implemented)
test/
  telegram.test.ts    # HMAC accept/reject/expiry cases
  stars.test.ts       # payment parsing + idempotency
```

## Entitlement schema (Firestore)

```
collection: entitlements
doc id:     `${telegramUserId}__${videoId}`   # one doc per user+video
fields:
  telegramUserId          number
  videoId                 string
  source                  "stars" | "manual"
  telegramPaymentChargeId string   # Telegram's idempotency key
  amount                  number   # Stars (XTR), integer
  currency                string   # "XTR"
  grantedAt               timestamp (server-set)
```

Entitlements are permanent (no expiry). Idempotency comes from the doc id: a
webhook retry or repeat purchase of the same video resolves to the same
document and is a no-op (the write runs in a transaction).

### Webhook auth & invoice payload

The webhook authenticates via the `X-Telegram-Bot-Api-Secret-Token` header
(`TELEGRAM_WEBHOOK_SECRET`, set as `secret_token` on `setWebhook`). The bot must
create invoices with `invoice_payload` of the form `vod:<videoId>` so the
payment can be mapped to a video.

## Local dry run

```sh
npm install
npm run dryrun        # tsc --noEmit + node:test HMAC suite
# credential-free boot:
DRY_RUN=1 npm run build && DRY_RUN=1 npm start
curl localhost:8080/healthz
```

`DRY_RUN=1` substitutes placeholder config and never constructs a GCP client, so
the skeleton boots with no credentials.

## Configuration (env)

See [`.env.example`](./.env.example). Key vars: `TELEGRAM_BOT_TOKEN`,
`GCP_PROJECT_ID`, `VIDEO_BUCKET`, `SIGNER_SERVICE_ACCOUNT`,
`SIGNED_URL_TTL_SECONDS` (600). The bot token comes from Secret Manager in
production — never bake it into the image.

## Deploy

`Dockerfile` builds a slim two-stage image (runs as the unprivileged `node`
user). `cloudbuild.yaml` builds, pushes to Artifact Registry, and deploys to
Cloud Run. **min-instances is configurable** via the `_MIN_INSTANCES`
substitution (maps to `--min-instances`). Auth to Firestore/GCS uses the
attached runtime service account (ADC) — no key files.

## Deferred (do not implement without sign-off)

- `src/storage.ts` `signManifestUrl` — the V4 signing ("video logic"). The
  `/manifest` route is wired (auth + entitlement check) but returns `501` until
  this is enabled.
