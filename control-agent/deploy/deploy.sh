#!/usr/bin/env bash
# Ayla control-agent — MANUAL deploy tool.
#
# This is the ONLY component with gcloud deploy permissions. It is triggered
# ONLY by the owner's explicit manual invocation — never on a schedule, never
# automatically, never by the monitor. There is no cron entry for this script.
#
# Usage:
#   ./deploy.sh delivery-service
#   ./deploy.sh pose-scoring-service
#   ./deploy.sh coaching-agent-service   # available once Phase 5 exists
set -euo pipefail

SERVICE="${1:-}"
REGION="${GCLOUD_REGION:-asia-east1}"
PROJECT="${GCP_PROJECT_ID:?set GCP_PROJECT_ID}"

case "$SERVICE" in
  delivery-service)      SRC="../../services/delivery-service" ;;
  pose-scoring-service)  SRC="../../services/pose-scoring-service" ;;
  coaching-agent-service)
    SRC="../../services/coaching-agent-service"
    if [ ! -d "$SRC" ]; then
      echo "coaching-agent-service does not exist yet (Phase 5)." >&2
      exit 1
    fi
    ;;
  *)
    echo "Usage: $0 {delivery-service|pose-scoring-service|coaching-agent-service}" >&2
    exit 2
    ;;
esac

echo ">>> Manual deploy of $SERVICE to project $PROJECT ($REGION)"
read -r -p "Confirm deploy of $SERVICE? [y/N] " ans
[ "$ans" = "y" ] || { echo "aborted"; exit 1; }

gcloud run deploy "$SERVICE" \
  --source "$SRC" \
  --project "$PROJECT" \
  --region "$REGION" \
  --no-allow-unauthenticated
