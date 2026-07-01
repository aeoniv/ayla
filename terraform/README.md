# terraform/ — plan-ready infra

Provisions the Ayla infrastructure for **both** backend services:

- a single private GCS **video bucket** (uniform access, public access enforced
  off, versioned),
- a **Firestore** native database (the only state store),
- two **Cloud Run** services — `delivery-service` and `pose-scoring-service` —
  with configurable `min_instances` (image tag ignored; pushed out-of-band),
- tightly-scoped **service accounts**, one per service,
- **Secret Manager** entries: telegram bot token, webhook secret, shared session
  secret, internal API key.

> **No `apply` from this scaffold without review.** Plan-ready only. Review the
> IAM and secret wiring first.

```sh
terraform init
terraform plan \
  -var project_id=my-project \
  -var video_bucket_name=my-globally-unique-vod-bucket \
  -var owner_telegram_id=123456789
```

## Service-account scoping (the important part)

`delivery-service-sa`:
| Capability | Role | Scope |
|---|---|---|
| Firestore read/write | `roles/datastore.user` | project |
| Read/write objects (feed signing + Phase 3 authoring uploads) | `roles/storage.objectUser` | **the one bucket only** |
| Mint V4 signed URLs (no key file) | `roles/iam.serviceAccountTokenCreator` | **itself only** |
| Read secrets | `secretAccessor` | bot token, webhook secret, session secret, internal key |

`pose-scoring-sa`:
| Capability | Role | Scope |
|---|---|---|
| Firestore read/write (references, attempts) | `roles/datastore.user` | project |
| Read videos / write reference JSON | `roles/storage.objectUser` | **the one bucket only** |
| Read secrets | `secretAccessor` | session secret, internal key |

No project-wide storage admin, no key files, no access to any other bucket.
V4 signing is done via IAM SignBlob (SA impersonating itself). Secrets reach
Cloud Run from Secret Manager at deploy time — never in state, image, or env
files.

The shared **session secret** and **internal API key** are read by both services
(delivery issues/pose verifies session JWTs; delivery calls pose `/score/authoring`
with the internal key). coaching-agent-service infra is added in Phase 5.
