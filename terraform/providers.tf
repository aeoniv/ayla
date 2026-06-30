terraform {
  required_version = ">= 1.5.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
  }

  # Plan-ready stub: configure a real backend before `terraform apply`.
  # backend "gcs" {
  #   bucket = "REPLACE_ME-tfstate"
  #   prefix = "ayla/delivery"
  # }
}

provider "google" {
  project = var.project_id
  region  = var.region
}
