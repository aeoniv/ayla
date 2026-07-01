# Ayla — coaching-agent-service (Phase 5)

Student-facing "AI coach". A **plain stateless Cloud Run service** calling the
**Gemini 3.1 Flash-Lite** API directly (owner's choice over Anthropic). Not
OpenClaw, no per-user process, no per-user agent instance — each request reads
current Firestore state fresh and responds, scaling exactly like
delivery-service.

## Endpoint
`POST /coach/next` (requires a Phase 1 session token). For the **caller's own**
user id (taken from the token, never the body):
1. reads their recent `attempts` and `watch_progress` from Firestore;
2. makes **one** Gemini call to (a) suggest the next movement/variant and (b)
   write a short personalized note referencing their recent score;
3. stores the result in `coaching_notes` and returns it.

The note is **encouraging but factual, grounded only in the student's own
history, never comparative** to other students (enforced in the system prompt).
The suggested movement is **grounded**: the server only accepts an id that was
in the candidate list AND exists in Firestore — a hallucinated id is dropped to
`null` rather than returned.

`coaching_notes` are stored so the feed can show them without regenerating on
every request.

## `requested_custom_skin` (placeholder only)
The request/response schema carries a `requested_custom_skin` field. This
service does **not** implement any generation behind it — the value is simply
echoed back. Custom avatar-skin generation will be a **separate queued job
system in a future phase**, not part of this stateless service.

## Config
- `SESSION_SECRET` — must match delivery-service (validates session JWTs).
- `GEMINI_API_KEY`, `GEMINI_MODEL` (default `gemini-3.1-flash-lite`).
- `GCP_PROJECT_ID`.

## Service account (least privilege)
- `roles/datastore.user` — read `attempts`/`watch_progress`/`movements`, write
  `coaching_notes`. No GCS access needed.
- Read the Gemini API key from Secret Manager (added to terraform in this phase).

## Run locally
```bash
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8082
```
