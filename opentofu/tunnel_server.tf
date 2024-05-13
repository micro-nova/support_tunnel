resource "google_service_account" "ts" {
  account_id   = "support-tunnel-server"
  display_name = "Service Account used for individual tunnel servers"
}

resource "google_service_account_iam_binding" "api_service_account_user" {
  service_account_id = google_service_account.ts.name
  role               = "roles/iam.serviceAccountUser"
  members = [
    "domain:${var.trusted_domain}"
  ]
}

resource "google_compute_firewall" "allow_wireguard" {
  name          = "allow-wireguard-${var.env}"
  direction     = "INGRESS"
  network       = google_compute_network.network.id
  source_ranges = ["0.0.0.0/0"]
  target_tags   = ["support-tunnel"]
  allow {
    protocol = "udp"
    ports    = ["20000-65534"]
  }
}

resource "google_compute_firewall" "allow_ssh" {
  name          = "allow-ssh-${var.env}"
  direction     = "INGRESS"
  network       = google_compute_network.network.id
  source_ranges = var.trusted_ip_ranges
  #target_service_accounts = [google_service_account.ts.email]

  target_tags = ["support-tunnel"]
  allow {
    protocol = "tcp"
    ports    = ["22"]
  }
}
