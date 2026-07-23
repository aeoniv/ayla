#!/usr/bin/env bash
# Ayla content seeding — owner-only admin calls. Requires jq + curl.
#
# Get TOKEN: open the Mini App in Telegram (as the OWNER), open devtools →
# Network, and copy the "Authorization: Bearer <...>" value from any request.
#
# Usage:
#   DELIVERY_URL=https://delivery-xxxx.run.app \
#   TOKEN=<owner session jwt> \
#   TEASER=./teaser.mp4 FULL=./full.mp4 \
#   V1_TEASER=./v1t.mp4 V1_FULL=./v1f.mp4 \
#   V2_TEASER=./v2t.mp4 V2_FULL=./v2f.mp4 \
#   ./seed.sh
set -euo pipefail

: "${DELIVERY_URL:?}"; : "${TOKEN:?}"
: "${TEASER:?}"; : "${FULL:?}"
: "${V1_TEASER:?}"; : "${V1_FULL:?}"; : "${V2_TEASER:?}"; : "${V2_FULL:?}"
AUTH="Authorization: Bearer $TOKEN"
JSON="Content-Type: application/json"

# Videos upload straight to GCS via a signed PUT URL (mirrors the app), then the
# create calls reference only the returned object path — no bytes proxied
# through delivery-service (which caps request bodies at 32 MiB).
upload() {  # $1=kind (teaser|full)  $2=local file  -> echoes the GCS object path
  local kind="$1" file="$2" resp path url
  resp=$(curl -sf "$DELIVERY_URL/admin/upload-url" -H "$AUTH" -H "$JSON" \
    -d "{\"kind\":\"$kind\",\"content_type\":\"video/mp4\"}")
  path=$(echo "$resp" | jq -r .path)
  url=$(echo "$resp" | jq -r .url)
  curl -sf -X PUT -H "Content-Type: video/mp4" --upload-file "$file" "$url" >/dev/null
  echo "$path"
}

echo "1) style"
STYLE_ID=$(curl -sf "$DELIVERY_URL/admin/style" -H "$AUTH" -F name=Taichi | jq -r .style_id)
echo "   style_id=$STYLE_ID"

echo "2) avatars (for the two variants)"
A1=$(curl -sf "$DELIVERY_URL/admin/avatar" -H "$AUTH" -F name="Blue Robe" -F style_id="$STYLE_ID" | jq -r .avatar_id)
A2=$(curl -sf "$DELIVERY_URL/admin/avatar" -H "$AUTH" -F name="Red Robe"  -F style_id="$STYLE_ID" | jq -r .avatar_id)
echo "   avatars=$A1 $A2"

echo "3) movement (upload teaser<=12s + full, then create with checkpoints)"
TP=$(upload teaser "$TEASER"); FP=$(upload full "$FULL")
MID=$(curl -sf "$DELIVERY_URL/admin/movement" -H "$AUTH" -H "$JSON" \
  -d "$(jq -nc --arg s "$STYLE_ID" --arg tp "$TP" --arg fp "$FP" \
    '{name:"Cloud Hands", style_id:$s, price_stars:50, checkpoint_seconds:[2,5,9,14], teaser_path:$tp, full_path:$fp}')" \
  | jq -r .movement_id)
echo "   movement_id=$MID"

echo "4) two style variants"
V1TP=$(upload teaser "$V1_TEASER"); V1FP=$(upload full "$V1_FULL")
curl -sf "$DELIVERY_URL/admin/movement-variant" -H "$AUTH" -H "$JSON" \
  -d "$(jq -nc --arg m "$MID" --arg s "$STYLE_ID" --arg a "$A1" --arg tp "$V1TP" --arg fp "$V1FP" \
    '{movement_id:$m, style_id:$s, avatar_id:$a, price_stars:20, teaser_path:$tp, full_path:$fp}')" | jq -c .
V2TP=$(upload teaser "$V2_TEASER"); V2FP=$(upload full "$V2_FULL")
curl -sf "$DELIVERY_URL/admin/movement-variant" -H "$AUTH" -H "$JSON" \
  -d "$(jq -nc --arg m "$MID" --arg s "$STYLE_ID" --arg a "$A2" --arg tp "$V2TP" --arg fp "$V2FP" \
    '{movement_id:$m, style_id:$s, avatar_id:$a, price_stars:20, teaser_path:$tp, full_path:$fp}')" | jq -c .

echo "DONE. Open the feed; movement '$MID' has 2 variants."
