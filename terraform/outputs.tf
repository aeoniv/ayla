output "video_bucket" {
  description = "The single bucket the delivery-service may sign URLs for."
  value       = google_storage_bucket.video.name
}

output "delivery_service_account" {
  description = "Runtime + signer identity for the delivery-service."
  value       = google_service_account.delivery.email
}

output "cloud_run_url" {
  description = "Delivery-service HTTPS endpoint."
  value       = google_cloud_run_v2_service.delivery.uri
}

output "pose_service_account" {
  description = "Runtime identity for the pose-scoring-service."
  value       = google_service_account.pose.email
}

output "pose_service_url" {
  description = "pose-scoring-service HTTPS endpoint."
  value       = google_cloud_run_v2_service.pose.uri
}

output "firestore_database" {
  description = "Firestore database name."
  value       = google_firestore_database.default.name
}
