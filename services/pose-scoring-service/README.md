# Ayla — pose-scoring-service (Phase 2)

Separate Cloud Run service. Runs MediaPipe Pose to (a) extract reference
landmarks from authored full videos and (b) score student attempts against them.

## Guided-flow model (Taichi form, pose-gated)
Practice is a **pose-gated flow**: the reference video pauses at each authored
checkpoint and resumes only when the student's live pose matches. Real-time
inference is **on-device** (client MediaPipe); the server does the authoritative
comparison and writes the attempt.

## Endpoints
| method | path | auth | notes |
|--------|------|------|-------|
| POST | `/score/authoring` | internal key | extract checkpoint poses from the **full** video at owner-marked timestamps |
| GET  | `/score/checkpoints/{movement}/{style}` | session + entitlement | checkpoint timestamps + tolerances to drive playback (no poses) |
| POST | `/score/checkpoint` | session + entitlement | real-time gate: match one checkpoint, returns `{matched, score, worst_region}` |
| POST | `/score/attempt` | session + entitlement | finalize: re-score run server-side, write `attempts` row |
| GET  | `/healthz` | — | liveness |

### `/score/authoring` (internal, not public)
Body `{ movement_id, style_id, full_video_path, checkpoint_seconds[],
default_tolerance }`. Guarded by `X-Internal-Key == INTERNAL_API_KEY`.
Downloads the full video, runs MediaPipe, picks the pose nearest each
owner-marked timestamp, uploads `{checkpoints:[…]}` to
`references/{movement}/{style}.json`, and stores small `checkpoints_meta`
(index, timestamp, tolerance) in Firestore.

### Student endpoints
All require a valid **Phase 1 session token** (HS256, shared `SESSION_SECRET`)
AND a valid **movement entitlement** — the full form is needed to practice, so
teaser/preview access alone is rejected with 403.
- `/score/checkpoints/…` returns only timestamps+tolerances so the client knows
  where to pause; reference poses stay server-side.
- `/score/checkpoint` compares the student's landmark vector to the checkpoint
  pose and returns `matched` (score ≥ tolerance) → client resumes playback.
- `/score/attempt` re-scores the submitted per-checkpoint poses server-side and
  writes one aggregate `attempts` row (never trusts client-computed scores).

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
