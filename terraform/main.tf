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

# (2) Read objects from THE ONE bucket only (needed to mint read signed URLs).
resource "google_storage_bucket_iam_member" "delivery_bucket_read" {
  bucket = google_storage_bucket.video.name
  role   = "roles/storage.objectViewer"
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
        name  = "VIDEO_BUCKET"
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
  ]
}
