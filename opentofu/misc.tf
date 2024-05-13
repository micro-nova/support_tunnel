data "google_project" "project" {}

resource "google_artifact_registry_repository" "docker" {
  repository_id = "support-tunnel-api-${var.env}"
  format        = "DOCKER"
  description   = "Storage for the Docker images for the support tunnel API, in env ${var.env}"
}
