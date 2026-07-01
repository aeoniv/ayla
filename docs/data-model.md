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
| `created_at`        | Timestamp       |                                            |

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
| `scope`                      | enum `movement` \| `subscription` | what was granted                      |
| `movement_id`                | string \| null        | set when `scope = movement`                       |
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

The prerequisite asks what a payment unlocks. The three options change
entitlement granularity and pricing surface:

| option | what a payment unlocks | pros | cons |
|--------|------------------------|------|------|
| **A. Single full video** | one `movement` in **one** style only | finest granularity, cheapest price point | user pays again to see the same movement in another avatar/style — likely feels punitive since variants are the *same* movement |
| **B. One movement, all its variants** *(recommended)* | one `movement_id` across **all** its `movement_style_variants` | matches the mental model — "I bought this movement", horizontal carousel stays unlocked, aligns with the shared 12s `watch_progress` cap keyed on `movement_id` | more content per purchase; needs `price_stars` tuned per movement |
| **C. Recurring Stars subscription** | everything, while `subscription_expires_at` is in the future | best recurring revenue, simplest UX ("unlock all") | requires Stars subscription webhook renewal handling; all-or-nothing hides per-movement pricing |

**Recommendation: B**, with the schema above also supporting C so you can add a
subscription tier later without migration. Reasons: (1) B is consistent with
the watch_progress cap being keyed on `movement_id`, so unlocking a movement
naturally unlocks every avatar/style of it; (2) it avoids the "I paid but the
next carousel card is locked" confusion of A.

**Please confirm A, B, C, or B+C before Phase 1's webhook is implemented.**

## ⚠️ FLAGGED FOR REVIEW #2 — watch_progress / 12s enforcement

Proposed enforcement (server-authoritative, client cannot bypass):

1. On playback, the frontend periodically POSTs elapsed seconds to
   `POST /playback/progress` with `{ movement_id, variant_id, seconds }`.
2. The server loads `watch_progress/${user_id}_${movement_id}`, and updates
   `seconds_watched = max(existing, min(reported, existing + delta))` — it
   **never trusts a lower number** and clamps implausible jumps, so cumulative
   seconds are monotonic per movement.
3. The cap is keyed on `movement_id`, **not** `variant_id`. Switching styles
   horizontally continues the same counter — no fresh 12 seconds.
4. When `seconds_watched >= 12` **and** the user has no entitlement covering
   that movement, the endpoint responds `locked: true`. The player stops
   playback at 12s (on any variant, any axis) and shows the unlock prompt,
   which calls `POST /payment/create-invoice`.
5. Entitled users are never capped: if an entitlement covers the movement, the
   server returns `locked: false` regardless of `seconds_watched`.

This enforcement is **server-side and authoritative** — the client stopping at
12s is a UX nicety, but the `locked` decision and the cumulative counter live
on the server. The same check gates scoring in Phase 2 (entitlement required,
teaser access alone is insufficient).

**Please confirm this enforcement design before Phase 1.**

---

## STOP — awaiting review

Per the build order, no service code will be written until you review this
file and confirm the two flagged decisions above.
