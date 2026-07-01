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

echo "1) style"
STYLE_ID=$(curl -sf "$DELIVERY_URL/admin/style" -H "$AUTH" -F name=Taichi | jq -r .style_id)
echo "   style_id=$STYLE_ID"

echo "2) avatars (for the two variants)"
A1=$(curl -sf "$DELIVERY_URL/admin/avatar" -H "$AUTH" -F name="Blue Robe" -F style_id="$STYLE_ID" | jq -r .avatar_id)
A2=$(curl -sf "$DELIVERY_URL/admin/avatar" -H "$AUTH" -F name="Red Robe"  -F style_id="$STYLE_ID" | jq -r .avatar_id)
echo "   avatars=$A1 $A2"

echo "3) movement (teaser<=12s + full + checkpoints)"
MID=$(curl -sf "$DELIVERY_URL/admin/movement" -H "$AUTH" \
  -F name="Cloud Hands" -F style_id="$STYLE_ID" -F price_stars=50 \
  -F 'checkpoint_seconds=[2,5,9,14]' \
  -F "teaser_video=@$TEASER" -F "full_video=@$FULL" | jq -r .movement_id)
echo "   movement_id=$MID"

echo "4) two style variants"
curl -sf "$DELIVERY_URL/admin/movement-variant" -H "$AUTH" \
  -F movement_id="$MID" -F style_id="$STYLE_ID" -F avatar_id="$A1" -F price_stars=20 \
  -F "teaser_video=@$V1_TEASER" -F "full_video=@$V1_FULL" | jq -c .
curl -sf "$DELIVERY_URL/admin/movement-variant" -H "$AUTH" \
  -F movement_id="$MID" -F style_id="$STYLE_ID" -F avatar_id="$A2" -F price_stars=20 \
  -F "teaser_video=@$V2_TEASER" -F "full_video=@$V2_FULL" | jq -c .

echo "DONE. Open the feed; movement '$MID' has 2 variants."
