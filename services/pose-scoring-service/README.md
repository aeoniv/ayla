# Ayla — pose-scoring-service (Phase 2)

Separate Cloud Run service. Runs MediaPipe Pose to (a) extract reference
landmarks from authored full videos and (b) score student attempts against them.

## Endpoints
| method | path | auth | notes |
|--------|------|------|-------|
| POST | `/score/authoring` | internal key | extract & store reference from the **full** video; called by Phase 3 |
| POST | `/score` | session + entitlement | score a student attempt, write to `attempts` |
| GET  | `/healthz` | — | liveness |

### `/score/authoring` (internal, not public)
Body `{ movement_id, style_id, full_video_path }`. Guarded by the
`X-Internal-Key` header matching `INTERNAL_API_KEY`. Downloads the full video
from GCS, runs MediaPipe, uploads the landmark JSON to
`references/{movement_id}/{style_id}.json`, and records it in Firestore.

### `/score` (student)
Multipart: `movement_id`, `style_id`, `video`. Requires:
1. a valid **Phase 1 session token** (`Authorization: Bearer …`, HS256 with the
   shared `SESSION_SECRET`), and
2. a valid **movement entitlement** (`has_movement_entitlement`) — scoring needs
   the full form, so teaser/preview access alone is rejected with 403.

Extracts attempt landmarks, compares to the stored reference, writes an
`attempts` row, and returns `{ attempt_id, score, worst_region, region_scores }`.

## Scoring method
- 33 MediaPipe Pose landmarks per frame; drop visibility, keep x/y/z.
- Per frame: translate to hip-center origin, scale by torso length → invariant
  to position and apparent size.
- Resample both sequences to `COMPARE_FRAMES` (64) over normalized time, then
  take per-landmark euclidean distance.
- Score = `100 * (1 - mean_distance / 0.5)`, clamped 0–100. Regions
  (head, left/right arm, torso, left/right leg) scored the same way; the region
  with the largest mean distance is reported as `worst_region`.

## ⚠️ Design note for review — per-(movement, style) references
The data model left reference storage shape "confirmed at Phase 2." Because
`/score` must compare against *"that style's stored reference,"* references are
stored at `movements/{id}/references/{style_id}` (one per style), not a single
field. For the movement's **home** style we also mirror
`reference_landmarks_path` / `_meta` onto the movement doc, matching
docs/data-model.md. This lets a movement carry a distinct reference per style
without schema migration. **Flag: confirm this shape.**

## Dependency on other phases
- Reads session JWTs issued by delivery-service → needs the **same
  `SESSION_SECRET`**.
- Reads `entitlements` written by the Phase 1 webhook.
- References are empty until Phase 3 authoring calls `/score/authoring`; `/score`
  returns 404 (no reference) until then — expected, not a bug.

## Service account (least privilege)
- `roles/datastore.user` (Firestore read/write: entitlements, references, attempts)
- object read/write on the **one** `GCS_BUCKET` only (read videos, write/read
  reference JSON) — nothing else.

## Config
`GCP_PROJECT_ID`, `GCS_BUCKET`, `SESSION_SECRET` (must equal delivery-service),
`INTERNAL_API_KEY`.

## Run locally
```bash
pip install -r requirements.txt   # heavy: mediapipe + opencv
uvicorn app.main:app --reload --port 8081
```
