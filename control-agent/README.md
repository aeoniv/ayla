# Ayla — control-agent (Phase 4)

Owner-only **operations** tool (OpenClaw config on a separate host). It does
**not** interact with students and does **not** appear in the app. Two agents
with strictly separated privileges.

## Agents
| agent | privilege | trigger | can it change anything? |
|-------|-----------|---------|-------------------------|
| **monitor** | read-only (HTTP GET + Telegram send) | every 5 min | **No** — cannot restart/deploy |
| **deploy** | `gcloud run deploy` | **manual only** | Yes, only when you run it by hand |

### monitor (`monitor/health_monitor.py`)
Persistent process. Polls each service's `/healthz` every `POLL_INTERVAL` (300s)
and DMs the owner after `FAIL_THRESHOLD` (2) **consecutive** failures; also sends
a recovery message. Stdlib only. Runs as a dedicated unprivileged user with **no
gcloud credentials** (see `monitor/ayla-monitor.service`). It polls
delivery-service, pose-scoring-service, and — once Phase 5 exists —
coaching-agent-service (leave its `SERVICES` url blank until then; the monitor
just skips it).

### deploy (`deploy/deploy.sh`)
The **only** component with deploy rights. Triggered **only** by your explicit
manual command (`./deploy.sh <service>`), with an interactive confirm. There is
**no cron/schedule** for it and the monitor cannot invoke it.

## Security boundaries (must be preserved)
1. **Tailscale-only.** The OpenClaw gateway binds to this host's `tailscale0` IP
   (`TAILSCALE_IP`), **never `0.0.0.0`**. `openclaw.yaml` also sets
   `deny_bind_addresses: [0.0.0.0, ::]` and `require_tailscale: true` as
   defense-in-depth. Verify after start:
   ```bash
   ss -tlnp | grep 8787     # must show 100.x.y.z:8787, NOT 0.0.0.0:8787
   ```
   This Tailscale-only rule is about the **control-agent gateway**, not the app
   services. The Cloud Run services (delivery/pose/coaching) are deployed
   `--allow-unauthenticated` on purpose: browsers (the Telegram Mini App) and
   Telegram's payment webhook call them directly and can't present a Google
   identity token, so auth is enforced **in-app** — session JWT, the webhook
   `secret_token`, and the internal API key — with the matching `allUsers`
   `run.invoker` binding defined in terraform.
2. **Privilege separation.** Run `monitor` and `deploy` as **separate OS
   users/hosts**. The monitor host has no gcloud deploy credentials; only the
   deploy host is authenticated with a service account holding
   `roles/run.developer` (+ build/artifact push). A compromise of the read-only
   monitor therefore cannot deploy.
3. **No auto-deploy, ever.** Nothing here schedules or auto-triggers a deploy.
   The monitor alerts; a human decides and runs `deploy.sh`.

## Setup (monitor host)
```bash
sudo useradd -r ayla-monitor
sudo mkdir -p /opt/ayla /etc/ayla
sudo cp -r . /opt/ayla/control-agent
sudo cp .env.example /etc/ayla/monitor.env   # fill SERVICES, CONTROL_BOT_TOKEN, OWNER_CHAT_ID
sudo cp monitor/ayla-monitor.service /etc/systemd/system/
sudo systemctl enable --now ayla-monitor
```
Owner must `/start` the ops bot once so it can DM alerts. Use a **separate ops
bot**, not the student-facing `Ayla_Bot`.

## Config
See `.env.example`: `SERVICES`, `CONTROL_BOT_TOKEN`, `OWNER_CHAT_ID`,
`TAILSCALE_IP` (monitor/gateway); `GCP_PROJECT_ID`, `GCLOUD_REGION` (deploy host).
