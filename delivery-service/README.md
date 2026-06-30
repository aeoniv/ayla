# delivery-service

Stateless Cloud Run HTTP service for the Telegram VoD app. All state lives in
Firestore; the container holds none, so any revision is interchangeable.

## Endpoints

| Method | Path | Status | Notes |
|---|---|---|---|
| `POST` | `/auth/telegram` | **implemented** | Validates `initData` HMAC-SHA256 against the bot token; rejects anything else. |
| `GET`  | `/manifest/:videoId` | wired, **signing stubbed (501)** | Auth via `Authorization: tma <initData>`, Firestore entitlement check, then a 10-min V4 signed URL. |
| `POST` | `/webhook/stars-payment` | **deferred (501)** | Stars `successful_payment`, idempotent on `telegram_payment_charge_id`. Pending entitlement-schema review. |
| `GET`  | `/healthz` | implemented | Liveness/readiness for the control-agent. |

## Layout

```
src/
  index.ts            # Express app + route wiring + /healthz
  config.ts           # env-only config (stateless)
  auth/telegram.ts    # initData HMAC validation  (implemented + tested)
  firestore.ts        # entitlement store; Entitlement schema is DRAFT
  storage.ts          # V4 signed-URL signer      (deferred stub)
  routes/
    auth.ts           # POST /auth/telegram
    manifest.ts       # GET  /manifest/:videoId
    starsWebhook.ts   # POST /webhook/stars-payment  (deferred)
test/
  telegram.test.ts    # HMAC accept/reject/expiry cases
```

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

- `src/storage.ts` `signManifestUrl` — the V4 signing ("video logic").
- `src/routes/starsWebhook.ts` + `firestore.ts` `grantEntitlement` — the
  payment write path, pending **entitlement-schema review**.
