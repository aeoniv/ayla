---
name: gcs-thumbnail-audit
description: >
  Scan the VoD bucket and report every video that is missing its thumbnail.
  Read-only: lists objects only, never writes, deletes, or mutates anything.
permissions:
  cloud:
    allow_readonly_list: true
  network:
    allow_egress:
      - storage.googleapis.com
---

# gcs-thumbnail-audit

Audits the video bucket for completeness of thumbnails.

## Layout assumption

Each video lives under a `videoId/` prefix:

```
gs://<bucket>/<videoId>/manifest.m3u8     # HLS manifest (the video exists)
gs://<bucket>/<videoId>/thumbnail.jpg     # poster image (what we audit for)
gs://<bucket>/<videoId>/segment-*.ts      # media segments
```

A video is **present** if it has a `manifest.m3u8`. It is **missing a
thumbnail** if it has a manifest but no `thumbnail.jpg`.

## What it does

1. Lists every `manifest.m3u8` in the bucket → the set of present videos.
2. Lists every `thumbnail.jpg` → the set of videos that have a thumbnail.
3. Reports the difference: videos present but with no thumbnail.

It performs **no writes**. It does not generate thumbnails; it only reports.

## Usage

```sh
VIDEO_BUCKET=my-vod-bucket ./audit.sh
# JSON output:
VIDEO_BUCKET=my-vod-bucket ./audit.sh --json
```

Exit code is `0` when every present video has a thumbnail, and `1` when one or
more are missing (so the heartbeat / CI can flag it).

## Boundary

This skill uses only `gsutil ls` (read-only list). It must never call
`gsutil cp`, `rm`, `rewrite`, or any mutating operation, and it must never
touch the delivery-service service-account credentials.
