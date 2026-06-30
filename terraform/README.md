# terraform/ — plan-ready infra stub

Provisions the delivery-service infrastructure:

- a single private GCS **video bucket** (uniform access, public access enforced
  off, versioned),
- a **Firestore** native database (the only state store),
- a **Cloud Run** service with configurable `min_instances`,
- a tightly-scoped **service account** for the service.

> **No `apply` from this scaffold.** This is plan-ready only. Review the IAM and
> the bot-token secret wiring first.

```sh
terraform init
terraform plan \
  -var project_id=my-project \
  -var video_bucket_name=my-globally-unique-vod-bucket \
  -var container_image=us-central1-docker.pkg.dev/my-project/delivery/delivery-service:abc123
```

## Service-account scoping (the important part)

`delivery-service-sa` gets exactly three capabilities and nothing else:

| Capability | Role | Scope |
|---|---|---|
| Firestore read/write | `roles/datastore.user` | project |
| Read objects (to sign read URLs) | `roles/storage.objectViewer` | **the one bucket only** |
| Mint V4 signed URLs (no key file) | `roles/iam.serviceAccountTokenCreator` | **itself only** |

Plus read access to the single `telegram-bot-token` Secret Manager secret.

There is **no** project-wide storage admin, **no** key file, and **no** access
to any other bucket. V4 signing is done via IAM SignBlob by the SA impersonating
itself, so no downloadable private key ever exists.

The bot token is delivered to Cloud Run from Secret Manager at deploy time — it
is never stored in state, the image, or env files.
