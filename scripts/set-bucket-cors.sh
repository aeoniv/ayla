#!/usr/bin/env bash
# Apply the browser-upload CORS rule to the Ayla video bucket WITHOUT terraform.
#
# The owner's browser uploads videos straight to GCS via signed PUT URLs
# (delivery-service /admin/upload-url). A cross-origin PUT needs the bucket to
# allow these origins + the PUT method + the Content-Type request header, or the
# upload fails with "TypeError: Failed to fetch" in the browser.
#
# This does the same thing as the cors block in terraform/main.tf, for when you
# don't want to run terraform. Edit scripts/bucket-cors.json if the Mini App is
# hosted on a different domain than the defaults.
#
# Usage:
#   BUCKET=your-video-bucket ./set-bucket-cors.sh
#   # BUCKET is the delivery-service GCS_BUCKET env / terraform video_bucket_name.
set -euo pipefail

: "${BUCKET:?set BUCKET (the delivery-service GCS_BUCKET, no gs:// prefix)}"
HERE="$(cd "$(dirname "$0")" && pwd)"
CORS="$HERE/bucket-cors.json"

echo ">>> Applying CORS from $CORS to gs://$BUCKET"
if command -v gcloud >/dev/null; then
  gcloud storage buckets update "gs://$BUCKET" --cors-file="$CORS"
  echo ">>> Current CORS on gs://$BUCKET:"
  gcloud storage buckets describe "gs://$BUCKET" --format="default(cors_config)"
elif command -v gsutil >/dev/null; then
  gsutil cors set "$CORS" "gs://$BUCKET"
  echo ">>> Current CORS on gs://$BUCKET:"
  gsutil cors get "gs://$BUCKET"
else
  echo "need either gcloud or gsutil on PATH" >&2
  exit 1
fi
