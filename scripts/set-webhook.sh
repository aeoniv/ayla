#!/usr/bin/env bash
# Ayla — register the Telegram webhook for the delivery-service.
#
# The delivery-service /payment/webhook handles TWO Telegram update types:
#   - pre_checkout_query : MUST be answered within 10s or the Stars payment is
#                          auto-cancelled and refunded ("paid but no access").
#   - message            : carries successful_payment, which grants entitlements.
# Both MUST be in allowed_updates. Registering with only ["message"] (an easy
# mistake) silently breaks every purchase because pre_checkout is never
# delivered, so the invoice never clears.
#
# Also sets secret_token so the service can verify the
# X-Telegram-Bot-Api-Secret-Token header — it MUST equal the service's
# TELEGRAM_WEBHOOK_SECRET env var.
#
# Usage:
#   BOT_TOKEN=123:abc \
#   DELIVERY_URL=https://delivery-xxxx.run.app \
#   WEBHOOK_SECRET=<same as TELEGRAM_WEBHOOK_SECRET> \
#   ./set-webhook.sh
#
# Verify afterwards:
#   curl -s "https://api.telegram.org/bot$BOT_TOKEN/getWebhookInfo" | jq .
# (allowed_updates should list "message" and "pre_checkout_query".)
set -euo pipefail

: "${BOT_TOKEN:?set BOT_TOKEN}"
: "${DELIVERY_URL:?set DELIVERY_URL (no trailing slash)}"
: "${WEBHOOK_SECRET:?set WEBHOOK_SECRET (must match TELEGRAM_WEBHOOK_SECRET)}"

URL="${DELIVERY_URL%/}/payment/webhook"
echo ">>> Registering webhook: $URL"

curl -sf "https://api.telegram.org/bot${BOT_TOKEN}/setWebhook" \
  -H "Content-Type: application/json" \
  -d "$(cat <<JSON
{
  "url": "${URL}",
  "secret_token": "${WEBHOOK_SECRET}",
  "allowed_updates": ["message", "pre_checkout_query"],
  "drop_pending_updates": false
}
JSON
)" | (command -v jq >/dev/null && jq . || cat)

echo ">>> Current webhook info:"
curl -sf "https://api.telegram.org/bot${BOT_TOKEN}/getWebhookInfo" \
  | (command -v jq >/dev/null && jq '{url, has_custom_certificate, pending_update_count, allowed_updates, last_error_message}' || cat)
