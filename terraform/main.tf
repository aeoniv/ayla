# Plan-ready stub for the Telegram VoD delivery-service infrastructure.
#
#   terraform init
#   terraform plan -var project_id=... -var video_bucket_name=...
#
# Do NOT `apply` from this scaffold without review. The IAM here implements the
# spec's "scoped only to Firestore + signed-URL signing on ONE bucket" rule.

# ---------------------------------------------------------------------------
# APIs
# ---------------------------------------------------------------------------
locals {
  services = [
    "run.googleapis.com",
    "firestore.googleapis.com",
    "storage.googleapis.com",
    "iam.googleapis.com",
    "iamcredentials.googleapis.com", # IAM SignBlob, for V4 signed URLs
    "secretmanager.googleapis.com",
    "artifactregistry.googleapis.com",
  ]
}

resource "google_project_service" "enabled" {
  for_each           = toset(local.services)
  service            = each.value
  disable_on_destroy = false
}

# ---------------------------------------------------------------------------
# Firestore (native mode) — the only state store.
# ---------------------------------------------------------------------------
resource "google_firestore_database" "default" {
  project     = var.project_id
  name        = "(default)"
  location_id = var.region
  type        = "FIRESTORE_NATIVE"

  depends_on = [google_project_service.enabled]
}

# ---------------------------------------------------------------------------
# The single VoD bucket. Private, uniform access, no public reads.
# ---------------------------------------------------------------------------
resource "google_storage_bucket" "video" {
  name                        = var.video_bucket_name
  location                    = var.region
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = false

  versioning {
    enabled = true
  }

  depends_on = [google_project_service.enabled]
}

# ---------------------------------------------------------------------------
# delivery-service runtime identity — scoped to NOTHING but what it needs.
# ---------------------------------------------------------------------------
resource "google_service_account" "delivery" {
  account_id   = "delivery-service-sa"
  display_name = "Telegram VoD delivery-service (Cloud Run runtime)"
}

# (1) Firestore read/write — project-level datastore.user.
resource "google_project_iam_member" "delivery_firestore" {
  project = var.project_id
  role    = "roles/datastore.user"
  member  = "serviceAccount:${google_service_account.delivery.email}"
}

# (2) Read/write objects on THE ONE bucket only. objectUser (not just Viewer)
#     because the Phase 3 authoring flow uploads teaser/full videos and rolls
#     back (deletes) them on failure. Still scoped to this single bucket.
resource "google_storage_bucket_iam_member" "delivery_bucket_rw" {
  bucket = google_storage_bucket.video.name
  role   = "roles/storage.objectUser"
  member = "serviceAccount:${google_service_account.delivery.email}"
}

# (3) Sign V4 URLs WITHOUT a key file: the SA impersonates itself via
#     IAM SignBlob. Granting tokenCreator on ITSELF (and nothing else) keeps the
#     signing capability tightly scoped.
resource "google_service_account_iam_member" "delivery_self_sign" {
  service_account_id = google_service_account.delivery.name
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = "serviceAccount:${google_service_account.delivery.email}"
}

# Bot token secret + access for the runtime SA (read-only, this secret only).
resource "google_secret_manager_secret" "bot_token" {
  secret_id = var.bot_token_secret_id
  replication {
    auto {}
  }
  depends_on = [google_project_service.enabled]
}

resource "google_secret_manager_secret_iam_member" "delivery_bot_token" {
  secret_id = google_secret_manager_secret.bot_token.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.delivery.email}"
}

# Webhook secret_token — echoed by Telegram so the service can reject forged
# webhook calls. Same scoped, read-only access for the runtime SA.
resource "google_secret_manager_secret" "webhook_secret" {
  secret_id = var.webhook_secret_id
  replication {
    auto {}
  }
  depends_on = [google_project_service.enabled]
}

resource "google_secret_manager_secret_iam_member" "delivery_webhook_secret" {
  secret_id = google_secret_manager_secret.webhook_secret.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.delivery.email}"
}

# Session-JWT signing secret — SHARED by delivery-service (issuer) and
# pose-scoring-service (verifier), so both must be able to read it.
resource "google_secret_manager_secret" "session_secret" {
  secret_id = var.session_secret_id
  replication {
    auto {}
  }
  depends_on = [google_project_service.enabled]
}

# Internal key for delivery -> pose /score/authoring. Both services read it.
resource "google_secret_manager_secret" "internal_api_key" {
  secret_id = var.internal_api_key_secret_id
  replication {
    auto {}
  }
  depends_on = [google_project_service.enabled]
}

resource "google_secret_manager_secret_iam_member" "delivery_session_secret" {
  secret_id = google_secret_manager_secret.session_secret.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.delivery.email}"
}

resource "google_secret_manager_secret_iam_member" "delivery_internal_key" {
  secret_id = google_secret_manager_secret.internal_api_key.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.delivery.email}"
}

# ---------------------------------------------------------------------------
# pose-scoring-service runtime identity — Firestore + the one bucket, nothing
# else. Reads videos, writes reference-landmark JSON, writes attempts.
# ---------------------------------------------------------------------------
resource "google_service_account" "pose" {
  account_id   = "pose-scoring-sa"
  display_name = "Ayla pose-scoring-service (Cloud Run runtime)"
}

resource "google_project_iam_member" "pose_firestore" {
  project = var.project_id
  role    = "roles/datastore.user"
  member  = "serviceAccount:${google_service_account.pose.email}"
}

resource "google_storage_bucket_iam_member" "pose_bucket_rw" {
  bucket = google_storage_bucket.video.name
  role   = "roles/storage.objectUser"
  member = "serviceAccount:${google_service_account.pose.email}"
}

resource "google_secret_manager_secret_iam_member" "pose_session_secret" {
  secret_id = google_secret_manager_secret.session_secret.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.pose.email}"
}

resource "google_secret_manager_secret_iam_member" "pose_internal_key" {
  secret_id = google_secret_manager_secret.internal_api_key.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.pose.email}"
}

# ---------------------------------------------------------------------------
# Cloud Run service (stateless). min-instances is configurable per spec.
# ---------------------------------------------------------------------------
resource "google_cloud_run_v2_service" "delivery" {
  name                = var.service_name
  location            = var.region
  ingress             = "INGRESS_TRAFFIC_ALL"
  deletion_protection = false

  template {
    service_account = google_service_account.delivery.email

    scaling {
      min_instance_count = var.min_instances
      max_instance_count = var.max_instances
    }

    containers {
      image = var.container_image

      env {
        name  = "GCP_PROJECT_ID"
        value = var.project_id
      }
      env {
        name  = "GCS_BUCKET"
        value = google_storage_bucket.video.name
      }
      env {
        name  = "SIGNER_SERVICE_ACCOUNT"
        value = google_service_account.delivery.email
      }
      env {
        name  = "SIGNED_URL_TTL_SECONDS"
        value = tostring(var.signed_url_ttl_seconds)
      }
      env {
        name  = "OWNER_TELEGRAM_ID"
        value = var.owner_telegram_id
      }
      # Phase 3 authoring calls pose-scoring-service internally.
      env {
        name  = "POSE_SCORING_URL"
        value = google_cloud_run_v2_service.pose.uri
      }
      env {
        name = "SESSION_SECRET"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.session_secret.secret_id
            version = "latest"
          }
        }
      }
      env {
        name = "INTERNAL_API_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.internal_api_key.secret_id
            version = "latest"
          }
        }
      }
      env {
        name = "TELEGRAM_BOT_TOKEN"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.bot_token.secret_id
            version = "latest"
          }
        }
      }
      env {
        name = "TELEGRAM_WEBHOOK_SECRET"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.webhook_secret.secret_id
            version = "latest"
          }
        }
      }
    }
  }

  depends_on = [
    google_project_service.enabled,
    google_secret_manager_secret_iam_member.delivery_bot_token,
    google_secret_manager_secret_iam_member.delivery_webhook_secret,
    google_secret_manager_secret_iam_member.delivery_session_secret,
    google_secret_manager_secret_iam_member.delivery_internal_key,
  ]

  # Images are pushed/updated out-of-band (gcloud run deploy / control-agent
  # deploy.sh). Terraform owns the infra, not the rolling image tag.
  lifecycle {
    ignore_changes = [template[0].containers[0].image]
  }
}

# ---------------------------------------------------------------------------
# pose-scoring-service (stateless Cloud Run). Not publicly invocable; called by
# delivery-service (authoring) and students with a valid session token.
# ---------------------------------------------------------------------------
resource "google_cloud_run_v2_service" "pose" {
  name                = var.pose_service_name
  location            = var.region
  ingress             = "INGRESS_TRAFFIC_ALL"
  deletion_protection = false

  template {
    service_account = google_service_account.pose.email

    scaling {
      min_instance_count = var.min_instances
      max_instance_count = var.max_instances
    }

    containers {
      image = var.pose_container_image

      env {
        name  = "GCP_PROJECT_ID"
        value = var.project_id
      }
      env {
        name  = "GCS_BUCKET"
        value = google_storage_bucket.video.name
      }
      env {
        name = "SESSION_SECRET"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.session_secret.secret_id
            version = "latest"
          }
        }
      }
      env {
        name = "INTERNAL_API_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.internal_api_key.secret_id
            version = "latest"
          }
        }
      }
    }
  }

  depends_on = [
    google_project_service.enabled,
    google_secret_manager_secret_iam_member.pose_session_secret,
    google_secret_manager_secret_iam_member.pose_internal_key,
  ]

  lifecycle {
    ignore_changes = [template[0].containers[0].image]
  }
}
