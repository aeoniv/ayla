# Ayla

AI-corrected movement coaching app (Telegram Mini App). Author Taichi-style
movement forms, sell access with Telegram Stars, and coach students through a
**pose-gated guided flow** where the reference video advances only as the student
matches each checkpoint pose.

## Repository layout
| path | what | phase |
|------|------|-------|
| `docs/data-model.md` | Firestore collections + the two reviewed enforcement rules | 0 |
| `services/delivery-service/` | FastAPI: Telegram auth, feed, variants, playback (12s), Stars payments, owner authoring | 1, 3 |
| `services/pose-scoring-service/` | MediaPipe: checkpoint authoring + real-time guided-flow scoring | 2 |
| `control-agent/` | OpenClaw ops tool: read-only monitor + manual-only deploy (Tailscale) | 4 |
| `services/coaching-agent-service/` | (Phase 5) stateless AI coach — Gemini 3.1 Flash-Lite | 5 |
| `terraform/` | GCP infra: Firestore, one private bucket, per-service least-privilege SAs, secrets, Cloud Run | infra |

## Core rules (never bypassed)
- 12s free preview on the **main** video only; variants stay blurred/locked until bought.
- `watch_progress` is cumulative per movement (keyed on `movement_id`), so switching style
  variants never grants a fresh 12s.
- Scoring/practice requires a **movement entitlement** — teaser access is never enough.
- Payments are **Telegram Stars (XTR) only**, empty provider token. No third-party provider.

## Infra
Provision with terraform (`terraform/`) — it defines Firestore, the single VoD
bucket (public access prevented), least-privilege runtime service accounts for
delivery + pose services, Secret Manager entries (bot token, webhook secret,
shared session secret, internal API key), and both Cloud Run services. Container
images are pushed out-of-band; terraform ignores the rolling image tag.

## Build order
Phases are built and reviewed in order: 0 → 1 → 2 → 3 → 4 → 5 (coaching) → 6
(frontend feed + practice) → 7 (admin page). One commit per phase.
