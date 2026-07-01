# Ayla — Data Model (Phase 0)

Firestore data model for **Ayla**, an AI-corrected movement coaching app.
This document defines collections, fields, and the two enforcement policies
flagged for owner review at the end. **No service code exists yet.** Nothing
in later phases has been assumed or stubbed.

> Convention: Firestore document IDs are the `id` fields below. Timestamps are
> Firestore `Timestamp`. `*_path` fields store **GCS object paths** (e.g.
> `bucket-relative/movements/<id>/full.mp4`), never signed URLs — signed URLs
> are generated per-request in the delivery-service (Phase 1). The GCS bucket
> is empty until content is uploaded via the Phase 3 authoring flow.

---

## Collections

### `users`
| field         | type                     | notes                                    |
|---------------|--------------------------|------------------------------------------|
| `id`          | string (doc id)          | internal user id                         |
| `telegram_id` | number                   | Telegram user id, unique                 |
| `role`        | enum `student` \| `owner`| owner determined by hardcoded env id too |
| `created_at`  | Timestamp                |                                          |

Indexes: `telegram_id` (unique lookup on `/auth/telegram`).

### `styles`
A lineage / discipline category (Taichi, Shaolin, Meihua). Not a cosmetic tag.
| field  | type            | notes                         |
|--------|-----------------|-------------------------------|
| `id`   | string (doc id) |                               |
| `name` | string          | e.g. `Taichi`, `Shaolin`      |

### `avatars`
A performer/clothing identity that belongs to a style.
| field      | type            | notes                   |
|------------|-----------------|-------------------------|
| `id`       | string (doc id) |                         |
| `name`     | string          |                         |
| `style_id` | string          | → `styles.id`           |

### `movements`
The canonical movement. Its reference landmarks come from the **full** video,
not the teaser.
| field                  | type            | notes                                             |
|------------------------|-----------------|---------------------------------------------------|
| `id`                   | string (doc id) |                                                   |
| `style_id`             | string          | → `styles.id` (the movement's home style)         |
| `name`                 | string          |                                                   |
| `teaser_video_path`    | string          | GCS path, teaser **≤ 12s** (enforced Phase 3)     |
| `full_video_path`      | string          | GCS path, full-length                             |
| `price_stars`          | number          | XTR price for per-movement unlock                 |
| `reference_landmarks`  | see below       | pose-landmark sequence extracted from **full**    |
| `created_at`           | Timestamp       | used by feed ranking                              |

`reference_landmarks` is written by the Phase 2 `/score/authoring` endpoint.
Because a landmark sequence per frame can be large, store it as:
- `reference_landmarks_path` (string, GCS path to a JSON/NPZ blob), **and**
- `reference_landmarks_meta` (map: `{ fps, frame_count, landmark_schema:
  "mediapipe_pose_33", extracted_at }`)

so the Firestore doc stays small. (Documented here; the blob-vs-inline choice
is an implementation detail confirmed at Phase 2.)

#### Guided flow: checkpoints (DECIDED 2026-07-01)
Ayla is a **pose-gated guided flow** (Taichi form style): during practice the
reference video **pauses at each checkpoint pose and resumes only when the
student's live pose matches** within tolerance. This is authored, not a raw
sequence:

- The **owner marks checkpoint timestamps** while authoring the full video
  (Phase 3). Phase 2 `/score/authoring` extracts the landmark pose at each
  marked time and stores an **ordered checkpoint list** per (movement, style)
  at `movements/{id}/references/{style_id}`:
  - Firestore doc: `{ landmarks_path, meta: { fps, landmark_schema,
    checkpoint_count }, checkpoints_meta: [{ index, timestamp_seconds,
    tolerance }] }` — small, no landmark arrays (Firestore disallows nested
    arrays).
  - GCS blob `references/{movement_id}/{style_id}.json`: the full checkpoint
    landmark data `{ checkpoints: [{ index, timestamp_seconds, landmarks:
    33×4 }] }`.
- **Real-time matching runs on-device** (client MediaPipe). The client extracts
  the student's landmarks and calls `POST /score/checkpoint` with the current
  checkpoint index + landmark vector; the server scores server-side and returns
  `{ matched, score, worst_region }`. On `matched=true` the client resumes the
  reference video to the next checkpoint's `timestamp_seconds`.
- On form completion the client submits the per-checkpoint matched landmarks to
  `POST /score/attempt`; the server **re-scores authoritatively** and writes one
  `attempts` row (aggregate `score` + worst `region`).

### `movement_style_variants`
The same movement performed by a **different avatar / clothing style**. This is
what the horizontal carousel scrolls between.
| field               | type            | notes                                      |
|---------------------|-----------------|--------------------------------------------|
| `id`                | string (doc id) |                                            |
| `movement_id`       | string          | → `movements.id`                           |
| `style_id`          | string          | → `styles.id`                              |
| `avatar_id`         | string          | → `avatars.id`                             |
| `teaser_video_path` | string          | GCS path, ≤ 12s                            |
| `full_video_path`   | string          | GCS path                                   |
| `price_stars`       | number          | XTR price for **this variant** (smaller than the movement price) |
| `created_at`        | Timestamp       |                                            |

Each variant is **individually purchasable** at its own (smaller) `price_stars`.
Buying the base movement does **not** unlock its variants — see Review #1.

Note: the base `movements` row is itself the "canonical" variant; the
carousel = base movement + all its `movement_style_variants`.

### `entitlements`
What a user has paid for. **Idempotent on `telegram_payment_charge_id`.**
Granularity depends on the model chosen in the review section below — schema
supports all three so the decision is reversible.
| field                        | type                  | notes                                             |
|------------------------------|-----------------------|---------------------------------------------------|
| `id`                         | string (doc id)       |                                                   |
| `user_id`                    | string                | → `users.id`                                      |
| `scope`                      | enum `movement` \| `variant` \| `subscription` | what was granted         |
| `movement_id`                | string \| null        | set when `scope = movement` (unlocks main video only) |
| `variant_id`                 | string \| null        | set when `scope = variant` (unlocks that one variant) |
| `subscription_tier`          | string \| null        | set when `scope = subscription`                   |
| `telegram_payment_charge_id` | string                | **unique** — dedup key for webhook idempotency    |
| `granted_at`                 | Timestamp             |                                                   |
| `subscription_expires_at`    | Timestamp \| null     | set for recurring Stars subscription              |

Idempotency: `/payment/webhook` upserts keyed on `telegram_payment_charge_id`
(document id = charge id, or a unique-constraint transaction) so a redelivered
Telegram update never grants twice.

### `watch_progress`
Tracks the 12-second free cap **per user per movement**, cumulative across
style-variant switches so a user cannot reset the free allowance by switching
avatars/styles mid-movement.
| field             | type            | notes                                                    |
|-------------------|-----------------|----------------------------------------------------------|
| `id`              | string (doc id) | composite `${user_id}_${movement_id}`                    |
| `user_id`         | string          | → `users.id`                                             |
| `movement_id`     | string          | → `movements.id` (**not** variant id — the cap is shared)|
| `seconds_watched` | number          | cumulative, monotonic, capped at 12 when un-entitled     |
| `updated_at`      | Timestamp       |                                                          |

Keyed on `movement_id`, **not** variant id — that is the mechanism that stops a
user gaining fresh seconds by switching horizontally.

### `attempts`
| field         | type            | notes                                        |
|---------------|-----------------|----------------------------------------------|
| `id`          | string (doc id) |                                              |
| `user_id`     | string          | → `users.id`                                 |
| `movement_id` | string          | → `movements.id`                             |
| `style_id`    | string          | which style the attempt was scored against   |
| `score`       | number          | similarity score                             |
| `region`      | string \| null  | body region that deviated most               |
| `timestamp`   | Timestamp       |                                              |

### `coaching_notes`
Short personalized notes from the coaching-agent-service (Phase 5), cached so
they are not regenerated on every feed request.
| field             | type            | notes                                   |
|-------------------|-----------------|-----------------------------------------|
| `id`              | string (doc id) |                                         |
| `user_id`         | string          | → `users.id`                            |
| `movement_id`     | string          | → `movements.id`                        |
| `generated_text`  | string          | encouraging, factual, non-comparative   |
| `suggested_next`  | map \| null     | `{ movement_id, variant_id? }`          |
| `generated_at`    | Timestamp       |                                         |

---

## ⚠️ FLAGGED FOR REVIEW #1 — Entitlement granularity

**DECIDED (owner, 2026-07-01): per-item purchase.**

- Buying a **movement** unlocks its **main video only** (`price_stars` on
  `movements`).
- Each **variant** is bought **separately**, at its own **smaller**
  `price_stars` on `movement_style_variants`.
- Entitlements therefore have `scope = movement` (movement_id) **or**
  `scope = variant` (variant_id). Buying the movement does **not** unlock
  variants; buying a variant does **not** unlock the movement.
- `scope = subscription` remains in the schema for a possible future
  "unlock all" tier, but is **not** used now.

Phase 1's webhook grants one entitlement row per purchased item, idempotent on
`telegram_payment_charge_id`.

## ⚠️ FLAGGED FOR REVIEW #2 — watch_progress / 12s enforcement

**DECIDED (owner, 2026-07-01): 12s free preview on the MAIN video only;
variants stay locked/blurred until purchased.**

Server-authoritative, client cannot bypass:

1. **Main video (base movement):** free preview up to 12s. Frontend
   periodically POSTs `POST /playback/progress`
   `{ movement_id, variant_id: null, seconds }`. Server loads
   `watch_progress/${user_id}_${movement_id}` and sets
   `seconds_watched = max(existing, min(reported, existing + delta))` —
   never trusts a lower number, clamps jumps, so the counter is monotonic.
2. When `seconds_watched >= 12` and the user has no `scope=movement`
   entitlement for it, the endpoint responds `locked: true`; player stops at
   12s and shows the unlock prompt → `POST /payment/create-invoice`.
3. **Variants:** **no free preview at all.** A variant plays only if the user
   has a `scope=variant` entitlement for that `variant_id`. Otherwise the
   carousel shows it **blurred** (poster/first frame blurred, no playback) with
   a buy prompt. `/playback/progress` for a variant with no entitlement returns
   `locked: true` immediately (0s allowed).
4. Entitled users are never capped for the item they own.
5. The same entitlement check gates scoring in Phase 2 — a valid entitlement
   for that movement/variant is required; preview access alone is insufficient.

The `locked` decision and cumulative counter live on the server; the client
stop/blur is only UX.

---

## STOP — awaiting review

Per the build order, no service code will be written until you review this
file and confirm the two flagged decisions above.
