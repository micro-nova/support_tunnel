# VPC network
resource "google_compute_network" "network" {
  name                    = "support-tunnel-${var.env}"
  auto_create_subnetworks = false
}

# proxy-only subnet
resource "google_compute_subnetwork" "proxy_subnet" {
  name          = "l7-ilb-proxy-subnet"
  ip_cidr_range = "10.0.0.0/24"
  purpose       = "REGIONAL_MANAGED_PROXY"
  role          = "ACTIVE"
  network       = google_compute_network.network.id
}

# api subnet
resource "google_compute_subnetwork" "api_subnet" {
  name          = "api-${var.env}"
  ip_cidr_range = "10.0.1.0/24"
  network       = google_compute_network.network.id
}

# tunnel server subnet
resource "google_compute_subnetwork" "ts_subnet" {
  name          = "ts-${var.env}"
  ip_cidr_range = "10.0.2.0/24"
  network       = google_compute_network.network.id
}

resource "google_compute_router" "router" {
  name    = "router-${var.env}"
  network = google_compute_network.network.name
}

resource "google_compute_router_nat" "nat" {
  name                               = "nat-${var.env}"
  router                             = google_compute_router.router.name
  source_subnetwork_ip_ranges_to_nat = "ALL_SUBNETWORKS_ALL_IP_RANGES"
  nat_ip_allocate_option             = "AUTO_ONLY"
}
