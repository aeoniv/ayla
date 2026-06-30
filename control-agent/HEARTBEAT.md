# HEARTBEAT — delivery-service health watchdog

**Cadence:** every 5 minutes (`heartbeat.interval_minutes: 5` in
`openclaw.config.yaml`).

**Goal:** detect when the Cloud Run `delivery-service` is unhealthy and alert
the owner on Telegram. **Do not auto-restart on the first failure** — only act
after **2 consecutive** failures, to avoid reacting to a single transient blip.

## State

The agent keeps a tiny counter in its working directory (state lives on the
control host, never in the delivery-service):

- `./state/consecutive_failures` — integer, starts at `0`.

## Procedure (run each tick)

1. **Probe the service.** Use a read-only describe — never a mutating call:

   ```sh
   gcloud run services describe "$SERVICE_NAME" \
     --region "$REGION" \
     --format='value(status.conditions[0].status)'
   ```

   Treat the tick as **healthy** only if:
   - the command exits `0`, AND
   - the `Ready` condition is `True`, AND
   - an HTTP probe of the service's `/healthz` returns `200` with
     `{"ok": true}`.

   ```sh
   curl -fsS --max-time 10 "$SERVICE_URL/healthz"
   ```

2. **On success:** reset `consecutive_failures` to `0`. No alert. Done.

3. **On failure:** increment `consecutive_failures`.

   - **failure #1** (`consecutive_failures == 1`):
     - Record the failure with a timestamp in `./state/last_failure.log`.
     - **Do nothing else.** No alert, no restart — wait for the next tick.

   - **failure #2+** (`consecutive_failures >= 2`):
     - **Send a Telegram DM alert** to the owner (see below).
     - Still **do not auto-restart** by default — restart is a separate, opt-in
       action and is out of scope for this scaffold. If/when enabled, a restart
       must go through an explicit, reviewed runbook, not the heartbeat.

## Alert format (Telegram DM)

Send via the Bot API using the **alert** bot token (not the delivery-service
bot token):

```sh
curl -fsS --max-time 10 \
  "https://api.telegram.org/bot${CONTROL_AGENT_ALERT_BOT_TOKEN}/sendMessage" \
  --data-urlencode "chat_id=${CONTROL_AGENT_ALERT_CHAT_ID}" \
  --data-urlencode "text=🚨 delivery-service unhealthy: ${N} consecutive failed health checks (region ${REGION}). Last ready status: ${STATUS}. Manual investigation required."
```

## Hard rules

- Read-only against Google Cloud: `describe` / `list` only. **Never**
  `gcloud run deploy`, `services update`, or anything that mutates the service.
- **Never** read, mount, or pass the delivery-service service-account
  credentials. The agent has its own minimal identity.
- All state is local to this host. The watchdog never writes to Firestore or
  the video bucket.
