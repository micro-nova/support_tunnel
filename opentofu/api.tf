resource "google_service_account" "api" {
  account_id   = "support-tunnel-api-${var.env}"
  display_name = "Service Account used for API service"
}

resource "google_project_iam_custom_role" "api_compute" {
  role_id     = "support_tunnel_api_${var.env}"
  title       = "support tunnel api role, ${var.env}"
  description = "Limited scope role for the API service to launch instances"
  permissions = [
    "compute.instances.create",
    "compute.images.getFromFamily",
    "compute.machineTypes.get",
    "compute.networks.get",
    "compute.diskTypes.get",
    "compute.disks.create",
    "compute.subnetworks.get",
    "compute.subnetworks.use",
    "compute.subnetworks.useExternalIp",
    "compute.instances.setMetadata",
    "compute.instances.setServiceAccount",
    "compute.instances.get",
    "compute.disks.list",
    "compute.zones.list",
    "compute.regions.list",
    "compute.regions.get",
  ]
}

resource "google_project_iam_binding" "api_compute" {
  project = data.google_project.project.project_id
  role    = google_project_iam_custom_role.api_compute.name
  members = [
    "serviceAccount:${google_service_account.api.email}"
  ]
}

resource "google_project_iam_binding" "api_sql_instance_user" {
  project = data.google_project.project.project_id
  role    = "roles/cloudsql.instanceUser"
  members = [
    "serviceAccount:${google_service_account.api.email}"
  ]
}

resource "google_project_iam_binding" "api_sql_client" {
  project = data.google_project.project.project_id
  role    = "roles/cloudsql.client"
  members = [
    "serviceAccount:${google_service_account.api.email}"
  ]
}

resource "google_project_iam_binding" "api_secrets_manager" {
  project = data.google_project.project.project_id
  role    = "roles/secretmanager.secretAccessor"
  members = [
    "serviceAccount:${google_service_account.api.email}"
  ]
}

resource "random_password" "jwt_secret" {
  length = 32
}

resource "google_secret_manager_secret" "jwt_secret" {
  secret_id = "jwt-secret-${var.env}"
  replication {
    auto {}
  }
}

resource "google_secret_manager_secret_version" "jwt_secret" {
  secret      = google_secret_manager_secret.jwt_secret.id
  secret_data = random_password.jwt_secret.result
}

resource "random_password" "admin_auth_token" {
  length = 32
}

resource "google_secret_manager_secret" "admin_auth_token" {
  secret_id = "support-tunnel-admin-token-${var.env}"
  replication {
    auto {}
  }
}

resource "google_secret_manager_secret_version" "admin_auth_token" {
  secret      = google_secret_manager_secret.admin_auth_token.id
  secret_data = random_password.admin_auth_token.result
}

resource "google_compute_region_network_endpoint_group" "api" {
  name                  = "api-rneg-${var.env}"
  network_endpoint_type = "SERVERLESS"
  region                = var.region

  cloud_run {
    service = google_cloud_run_v2_service.api.name
  }
}

resource "google_compute_backend_service" "api" {
  name                  = "api-backend-service-${var.env}"
  load_balancing_scheme = "EXTERNAL_MANAGED"

  backend {
    group = google_compute_region_network_endpoint_group.api.id
  }
}

resource "google_cloud_run_v2_service" "api" {
  name         = "api-${var.env}"
  location     = var.region
  ingress      = "INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER"
  launch_stage = "BETA" # permits use of direct VPC networking

  template {
    service_account = google_service_account.api.email
    containers {
      image = "${var.region}-docker.pkg.dev/${data.google_project.project.project_id}/${google_artifact_registry_repository.docker.name}/api:latest"

      ports {
        container_port = 8000
      }

      resources {
        cpu_idle = true # allows idling of the CPU when no requests are being processed.
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
      }

      env {
        name  = "ENV"
        value = var.env
      }

      env {
        name  = "PROJECT_ID"
        value = data.google_project.project.project_id
      }

      env {
        name = "SQL_PASSWORD"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret_version.sql_password.secret
            version = "latest"
          }
        }
      }

      env {
        name = "JWT_SECRET"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret_version.jwt_secret.secret
            version = "latest"
          }
        }
      }

      env {
        name = "ADMIN_AUTH_TOKEN"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret_version.admin_auth_token.secret
            version = "latest"
          }
        }
      }
    }

    vpc_access {
      network_interfaces {
        subnetwork = google_compute_subnetwork.api_subnet.name
      }
      egress = "PRIVATE_RANGES_ONLY"
    }
  }

  lifecycle {
    ignore_changes = [
      template["labels"],
      client,
      client_version
    ]
  }
}

# the below permits everyone to invoke this service. since it's a public API, this is
# desirable.
data "google_iam_policy" "noauth" {
  binding {
    role = "roles/run.invoker"
    members = [
      "allUsers",
    ]
  }
}

resource "google_cloud_run_v2_service_iam_policy" "noauth" {
  name     = google_cloud_run_v2_service.api.name
  location = google_cloud_run_v2_service.api.location

  policy_data = data.google_iam_policy.noauth.policy_data
}
