resource "google_compute_global_address" "private_ip_address" {
  name          = "private-ip-address"
  purpose       = "VPC_PEERING"
  address_type  = "INTERNAL"
  prefix_length = 16
  network       = google_compute_network.network.id
}

resource "google_service_networking_connection" "private_vpc_connection" {
  network                 = google_compute_network.network.id
  service                 = "servicenetworking.googleapis.com"
  reserved_peering_ranges = [google_compute_global_address.private_ip_address.name]
}

resource "google_sql_database_instance" "main" {
  name             = "api-${var.env}"
  database_version = "MYSQL_8_0"

  deletion_protection = var.env == "dev" ? false : true
  depends_on          = [google_service_networking_connection.private_vpc_connection]

  settings {
    tier = "db-f1-micro"
    ip_configuration {
      ipv4_enabled                                  = false
      private_network                               = google_compute_network.network.id
      enable_private_path_for_google_cloud_services = true
    }
  }
}

resource "google_sql_database" "db" {
  name     = "support-tunnel"
  instance = google_sql_database_instance.main.name
}

# This is a real big bummer. GCP does not support creating users backed by IAM with GRANTs;
# they get created with zero permissions. There are two paths:
# * manage the grant with a `mysql_grant`-like resource, but that requires terraform having
#   init-time access to the mysql instance, which is hard due to deps and networking, or
# * creating a manual user, not backed by IAM, which gets superuser access. this means the
#   password needs to be created & stored via secrets manager, or worse via userdata; it 
#   also means the password would live cleartext in the terraform state. However, our
#   networking protects the sql instance, and it's pretty straightforward. Additionally,
#   our app already needs close to superuser perms.
# We've opted for the second option.
# feature requests open with Google:
# https://issuetracker.google.com/issues/220759790
# https://issuetracker.google.com/issues/227942163
# 
# To force-rotate a password, `terraform taint random_password.sql_password; terraform apply`;
# this will recreate the instance group manager and take down the api for ~20 minutes, so take heed.

resource "random_password" "sql_password" {
  length = 24
}

resource "google_secret_manager_secret" "sql_password" {
  secret_id = "sql-password-${var.env}"
  replication {
    auto {}
  }
}

resource "google_secret_manager_secret_version" "sql_password" {
  secret      = google_secret_manager_secret.sql_password.id
  secret_data = random_password.sql_password.result
}

resource "google_sql_user" "user" {
  name     = "api-${var.env}"
  password = random_password.sql_password.result
  instance = google_sql_database_instance.main.name
  type     = "BUILT_IN"
}
