# control-agent (OpenClaw watchdog)

An OpenClaw agent that **observes** the Cloud Run `delivery-service` from a
separate host. It does three things and nothing more:

1. **Health heartbeat** — every 5 minutes, describes the Cloud Run service and
   probes `/healthz`. Alerts the owner on Telegram after **2 consecutive**
   failures (never on the first). See [`HEARTBEAT.md`](./HEARTBEAT.md).
2. **Thumbnail audit** — the `gcs-thumbnail-audit` skill lists the video bucket
   (read-only) and reports videos missing a thumbnail. See
   [`skills/gcs-thumbnail-audit/`](./skills/gcs-thumbnail-audit/).
3. **Alerting** — posts to the owner's Telegram DM using its *own* alert bot.

It runs on a **separate VPS/host** from the delivery-service and shares no
credentials with it.

## Networking — Tailscale only, never 0.0.0.0

This host **must** run behind [Tailscale](https://tailscale.com/). The OpenClaw
gateway binds to the host's Tailscale IP (or loopback) and **must never bind to
`0.0.0.0`** — there is no reason for this watchdog to be reachable from the
public internet.

- `openclaw.config.yaml` sets `gateway.bind_address` to the Tailscale IP and
  `gateway.require_tailscale: true`.
- Treat a `0.0.0.0` bind as a misconfiguration; the config comments call this
  out and OpenClaw refuses to start when it detects a public bind.
- No inbound firewall ports for the gateway. Reach it over the tailnet.

## Setup

```sh
# 1. Join the tailnet
tailscale up

# 2. Provide ONLY the alert bot secrets (NOT the delivery-service bot token)
export CONTROL_AGENT_ALERT_BOT_TOKEN=...    # a separate "ops alert" bot
export CONTROL_AGENT_ALERT_CHAT_ID=...      # owner's chat id

# 3. Provide the service coordinates the heartbeat probes
export SERVICE_NAME=delivery-service
export REGION=us-central1
export SERVICE_URL=https://delivery-service-xxxx-uc.a.run.app
export VIDEO_BUCKET=my-vod-bucket

# 4. Start OpenClaw with this config
openclaw run --config openclaw.config.yaml
```

The agent authenticates to Google Cloud with its **own** minimal identity
(read-only describe + bucket list). It must never be given the
delivery-service's service-account key.

## What this agent is NOT allowed to do

These are enforced by the deny-list in `openclaw.config.yaml`:

- No shell access outside its working directory (`/opt/ayla/control-agent`).
- No reading of the delivery-service service-account credentials.
- No minting of SA keys, no printing of access tokens.
- No `gcloud run deploy` / `services update` — it cannot mutate the service.
- No writes to Firestore or the video bucket.

See the top-level [`README.md`](../README.md) for the full security boundary
between this agent and the delivery-service.
