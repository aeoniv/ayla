#!/usr/bin/env bash
#
# gcs-thumbnail-audit — report videos in the VoD bucket that lack a thumbnail.
#
# READ-ONLY. Uses `gsutil ls` exclusively. Never copies, removes, or rewrites.
#
# Usage:
#   VIDEO_BUCKET=my-bucket ./audit.sh [--json]
#
# Exit codes:
#   0  every present video has a thumbnail
#   1  one or more videos are missing a thumbnail
#   2  usage / environment error
set -euo pipefail

JSON=0
[[ "${1:-}" == "--json" ]] && JSON=1

if [[ -z "${VIDEO_BUCKET:-}" ]]; then
  echo "error: VIDEO_BUCKET env var is required" >&2
  exit 2
fi

bucket="gs://${VIDEO_BUCKET}"

# Defensive: this skill must only ever list. Bail if anyone wires in a verb.
guard() {
  case "$1" in
    ls) : ;;
    *) echo "error: gcs-thumbnail-audit may only 'ls' (got '$1')" >&2; exit 2 ;;
  esac
}

list_suffix() {
  # Lists object paths whose basename matches $1 across all videoId/ prefixes.
  guard ls
  gsutil ls "${bucket}/**/$1" 2>/dev/null || true
}

# videoId = the path component immediately before the matched file.
extract_ids() {
  sed -E "s#^${bucket}/(.+)/[^/]+\$#\1#"
}

present="$(list_suffix manifest.m3u8 | extract_ids | sort -u)"
with_thumb="$(list_suffix thumbnail.jpg | extract_ids | sort -u)"

# Present videos that have no thumbnail.
missing="$(comm -23 <(printf '%s\n' "$present" | sed '/^$/d') \
                    <(printf '%s\n' "$with_thumb" | sed '/^$/d'))"

count_missing=$(printf '%s\n' "$missing" | sed '/^$/d' | wc -l | tr -d ' ')

if [[ "$JSON" == "1" ]]; then
  printf '{"bucket":"%s","missing_count":%s,"missing":[' "$VIDEO_BUCKET" "$count_missing"
  first=1
  while IFS= read -r id; do
    [[ -z "$id" ]] && continue
    [[ $first -eq 0 ]] && printf ','
    printf '"%s"' "$id"
    first=0
  done <<< "$missing"
  printf ']}\n'
else
  if [[ "$count_missing" -eq 0 ]]; then
    echo "OK: all $(printf '%s\n' "$present" | sed '/^$/d' | wc -l | tr -d ' ') videos have thumbnails."
  else
    echo "MISSING THUMBNAILS ($count_missing):"
    printf '%s\n' "$missing" | sed '/^$/d' | sed 's/^/  - /'
  fi
fi

[[ "$count_missing" -eq 0 ]]
