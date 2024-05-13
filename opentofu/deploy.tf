data "github_repository" "repo" {
  full_name = var.repo_name
}

resource "google_iam_workload_identity_pool" "github" {
  workload_identity_pool_id = "github-${var.env}"
}

resource "google_iam_workload_identity_pool_provider" "github" {
  workload_identity_pool_id          = google_iam_workload_identity_pool.github.workload_identity_pool_id
  workload_identity_pool_provider_id = "github"
  display_name                       = "Github"
  description                        = "OIDC identity pool provider for automated deployments from Github -> Cloud Run"
  attribute_condition                = "assertion.repository_owner == 'micro-nova' && assertion.repository_id == '${data.github_repository.repo.repo_id}'"
  attribute_mapping = {
    "google.subject"             = "assertion.sub"
    "attribute.actor"            = "assertion.actor"
    "attribute.repository"       = "assertion.repository"
    "attribute.repository_owner" = "assertion.repository_owner"
    "attribute.repository_id"    = "assertion.repository_id"
  }
  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }
}

resource "google_service_account" "github" {
  account_id   = "github-deploy-${var.env}"
  display_name = "Service account used for deploying new Docker images from github"
}

resource "google_service_account_iam_binding" "github" {
  service_account_id = google_service_account.github.name
  role               = "roles/iam.workloadIdentityUser"
  members = [
    "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github.name}/attribute.repository/${data.github_repository.repo.full_name}"
  ]
}

resource "google_service_account_iam_binding" "deploy_act_as_api" {
  service_account_id = google_service_account.api.name
  role               = "roles/iam.serviceAccountUser"
  members = [
    "serviceAccount:${google_service_account.github.email}"
  ]
}

resource "google_project_iam_binding" "github_deploy_image" {
  project = data.google_project.project.project_id
  role    = "roles/artifactregistry.createOnPushWriter"
  members = [
    "serviceAccount:${google_service_account.github.email}"
  ]
}

resource "google_project_iam_binding" "github_deploy_service" {
  project = data.google_project.project.project_id
  role    = "roles/run.developer"
  members = [
    "serviceAccount:${google_service_account.github.email}"
  ]
  /* TODO: fix this condition
  condition {
    title = "deploy_only_specified_api_service_${var.env}"
    description = "Ensures this role is only used with the API service for a particular environment"
    expression = "resource.name.endsWith('services/api-${var.env}')"
  }
  */
}

resource "github_repository_environment" "repo" {
  repository  = data.github_repository.repo.name
  environment = var.env
}

resource "github_actions_environment_secret" "oidc_workload_provider" {
  repository      = data.github_repository.repo.name
  environment     = github_repository_environment.repo.environment
  secret_name     = "WORKLOAD_IDENTITY_PROVIDER"
  plaintext_value = google_iam_workload_identity_pool_provider.github.name
}

resource "github_actions_environment_secret" "project_id" {
  repository      = data.github_repository.repo.name
  environment     = github_repository_environment.repo.environment
  secret_name     = "PROJECT_ID"
  plaintext_value = data.google_project.project.project_id
}

resource "github_actions_environment_secret" "deploy_service_account" {
  repository      = data.github_repository.repo.name
  environment     = github_repository_environment.repo.environment
  secret_name     = "DEPLOY_SERVICE_ACCOUNT"
  plaintext_value = google_service_account.github.email
}

resource "github_actions_environment_secret" "docker_repo" {
  repository      = data.github_repository.repo.name
  environment     = github_repository_environment.repo.environment
  secret_name     = "DOCKER_REPO"
  plaintext_value = "${var.region}-docker.pkg.dev/${data.google_project.project.project_id}/${google_artifact_registry_repository.docker.name}"
}

resource "github_actions_environment_variable" "docker_registry" {
  repository    = data.github_repository.repo.name
  environment   = github_repository_environment.repo.environment
  variable_name = "DOCKER_REGISTRY"
  value         = "${var.region}-docker.pkg.dev"
}
