# Ayla — frontend (Phase 6)

Telegram Mini App (React + Vite + TypeScript). The testable core loop: a
two-axis feed and a pose-gated practice screen.

## Screens
### Feed (`src/screens/Feed.tsx`, `components/MovementCard.tsx`)
- **Vertical scroll** (Reels-style, scroll-snap + IntersectionObserver): moves
  between movements, autoplays the active movement's teaser (`GET /feed`).
- **Horizontal carousel** on the current movement: index 0 is the original,
  1..n are `movement_style_variants` (`GET /movement/:id/variants`).
- **12s enforcement (main video):** while playing, the card polls
  `POST /playback/progress` every second; when the server returns `locked` the
  video pauses and an unlock prompt appears. The cap is server-side and keyed on
  `movement_id`, so switching variants never grants a fresh 12s.
- **Variants:** shown **blurred with no playback** unless entitled; the client
  only ever receives a playable URL for owned variants.
- **Pay:** unlock buttons call `POST /payment/create-invoice` and open the Stars
  invoice via the Telegram `openInvoice` WebApp API. On `paid`, state refreshes.

### Practice (`src/screens/Practice.tsx`)
Reachable only for an **entitled** movement (the "Practice" button appears once
the main video is owned; the full video endpoint is entitlement-gated too).
Implements the **guided flow** (per the Phase 2 revision, not a single `/score`
upload):
1. Loads the full reference video (`GET /movement/:id/full`) and checkpoint
   timestamps (`GET /score/checkpoints/...`), starts the webcam, and inits
   **on-device MediaPipe** (`@mediapipe/tasks-vision`).
2. Plays the reference video; at each checkpoint timestamp it **pauses**.
3. While paused, it extracts the student's landmarks on-device and calls
   `POST /score/checkpoint` (~2/s). On `matched`, it records the pose and
   **resumes** to the next checkpoint. Live hint shows the worst body region.
4. On the last checkpoint it calls `POST /score/attempt` (server re-scores) then
   `POST /coach/next`, and shows the coaching note + suggested next movement.

## Config
`.env` (see `.env.example`): `VITE_DELIVERY_URL`, `VITE_POSE_URL`,
`VITE_COACH_URL` — the three Cloud Run service URLs. One session token (from
`POST /auth/telegram`, validated over Telegram initData HMAC) is sent to all
three.

## Dev
```bash
npm install
npm run typecheck      # tsc --noEmit
npm run build          # tsc -b + vite build
npm run dev            # local; must be opened inside Telegram for initData
```
Outside Telegram there is no `initData`, so the app shows a sign-in notice —
test via the BotFather Mini App URL (or a tunnel) so real initData is present.
The camera/MediaPipe practice flow requires HTTPS and camera permission.
