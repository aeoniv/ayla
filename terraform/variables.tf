variable "project_id" {
  type        = string
  description = "GCP project that hosts Firestore, the video bucket, and Cloud Run."
}

variable "region" {
  type        = string
  description = "Region for Cloud Run, the bucket, and Firestore."
  default     = "us-central1"
}

variable "video_bucket_name" {
  type        = string
  description = "Globally-unique name for the single VoD bucket the service may sign URLs for."
}

variable "service_name" {
  type        = string
  description = "Cloud Run service name."
  default     = "delivery-service"
}

variable "container_image" {
  type        = string
  description = "Fully-qualified container image for the delivery-service."
  default     = "us-central1-docker.pkg.dev/REPLACE_ME/delivery/delivery-service:latest"
}

variable "min_instances" {
  type        = number
  description = "Cloud Run min-instances (configurable per spec)."
  default     = 0
}

variable "max_instances" {
  type        = number
  description = "Cloud Run max-instances."
  default     = 10
}

variable "signed_url_ttl_seconds" {
  type        = number
  description = "Signed-URL lifetime (spec: 600 = 10 minutes)."
  default     = 600
}

variable "bot_token_secret_id" {
  type        = string
  description = "Secret Manager secret id holding the Telegram bot token."
  default     = "telegram-bot-token"
}
