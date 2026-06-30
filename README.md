# ayla — Telegram VoD delivery

A scaffold for selling and delivering video-on-demand through a Telegram Mini
App. Two **independently deployed** components:

| Component | Where it runs | Job |
|---|---|---|
| [`delivery-service/`](./delivery-service) | Cloud Run (stateless) | Auth (Telegram initData), entitlement checks, time-limited signed URLs, Stars payment webhook |
| [`control-agent/`](./control-agent) | A separate VPS, behind Tailscale | Operational watchdog: health heartbeat, bucket thumbnail audit, Telegram alerts |
| [`terraform/`](./terraform) | — | Plan-ready infra: bucket, Firestore, Cloud Run, scoped IAM |

> **Status: skeleton + payments.** The Telegram initData HMAC auth and the
> Stars payment webhook (idempotent entitlement writes) are implemented and
> tested against the reviewed entitlement schema. The remaining deferred piece
> is the manifest V4 signed-URL minting ("video logic"), which returns `501`
> until enabled. See "Deferred work" below.

## ⚠️ Security boundary between the two components — READ THIS

**The delivery-service and the control-agent are mutually distrusting and share
no credentials.** The delivery-service is the *only* component with an identity
that can read/write Firestore and mint signed URLs for the video bucket; its
service account is scoped to exactly that and nothing else (Firestore
read/write, object-read on one named bucket, and self-impersonation for V4
signing). The control-agent is an *outside observer*: it runs on a different
host, authenticates with its own minimal read-only identity, and is explicitly
denied — via the OpenClaw deny-list — any shell access outside its working
directory, any access to the delivery-service's service-account credentials,
any ability to mint SA keys or print access tokens, and any `gcloud run deploy`
/ `update` that could mutate the service. It can *describe* the service and
*list* the bucket; it cannot *become* the service or write to its state. A full
compromise of the control-agent therefore yields no entitlement-granting,
no signed URLs, and no payment authority — only the ability to read health and
raise (or suppress) alerts. The control host runs behind Tailscale with the
gateway never bound to `0.0.0.0`, so it has no public attack surface to begin
with.

## delivery-service (Cloud Run, stateless)

Node.js / TypeScript HTTP service. **Why TypeScript over Python/FastAPI:** the
Telegram WebApp `initData` HMAC scheme and Stars webhook payloads are trivial to
model in TS, `@google-cloud/storage` has first-class V4 signed-URL support via
IAM SignBlob (no key file), and a single small Express app keeps the stateless
Cloud Run surface minimal. Either stack would work; TS won on ecosystem fit for
the Telegram + GCS signing path.

Endpoints:

- `POST /auth/telegram` — validates Telegram WebApp `initData` via HMAC-SHA256
  against the bot token; rejects anything that does not verify. **Implemented.**
- `GET /manifest/:videoId` — authenticates, checks Firestore entitlement, and
  returns a 10-minute V4 signed URL for the HLS manifest. **Wired; signing is a
  deferred stub (501).**
- `POST /webhook/stars-payment` — handles Telegram Stars `successful_payment`,
  authenticated via the webhook secret-token header, idempotent on
  `telegram_payment_charge_id`, writes the entitlement to Firestore.
  **Implemented** against the reviewed schema (see below).
- `GET /healthz` — liveness/readiness, polled by the control-agent.

All state lives in Firestore; the service holds none. See
[`delivery-service/README.md`](./delivery-service/README.md).

### Dry run

```sh
cd delivery-service
npm install
npm run dryrun     # typecheck + HMAC auth tests
DRY_RUN=1 npm run build && DRY_RUN=1 npm start   # boots with no GCP creds
```

## control-agent (OpenClaw, separate host)

See [`control-agent/README.md`](./control-agent/README.md). Heartbeat polls the
Cloud Run health endpoint every 5 minutes and alerts the owner's Telegram DM
only after **2 consecutive** failures (never on the first, and it does not
auto-restart). Ships one skill, `gcs-thumbnail-audit`, that reports videos
missing a thumbnail. Must run behind Tailscale; gateway never binds `0.0.0.0`.

## Entitlement schema (reviewed)

`entitlements/{telegramUserId}__{videoId}` — one doc per user+video, permanent
(no expiry). Fields: `telegramUserId`, `videoId`, `source` (`stars`|`manual`),
`telegramPaymentChargeId`, `amount`, `currency` (`XTR`), `grantedAt`.
Idempotency comes from the doc id: a webhook retry or repeat purchase of the
same video is a transactional no-op. Full detail in
[`delivery-service/README.md`](./delivery-service/README.md#entitlement-schema-firestore).

## Deferred work (do not start without sign-off)

1. **Manifest signed-URL minting** ("video logic") — wired in
   `src/storage.ts` as a stub; the `/manifest` route returns `501` until it is
   enabled. Turn this on once you're ready to serve real HLS manifests.

## Repository layout

```
.
├── delivery-service/    # Cloud Run service (TS/Express)
├── control-agent/       # OpenClaw watchdog (config, HEARTBEAT, skills)
├── terraform/           # plan-ready infra stub
└── README.md            # you are here
```
