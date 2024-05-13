resource "google_compute_target_https_proxy" "api" {
  name            = "api-target-https-proxy-${var.env}"
  url_map         = google_compute_url_map.api.id
  certificate_map = "//certificatemanager.googleapis.com/${google_certificate_manager_certificate_map.certificate_map.id}"
}

resource "google_compute_url_map" "api" {
  name = "api-url-map-${var.env}"

  default_service = google_compute_backend_service.api.self_link

  host_rule {
    hosts        = ["support-tunnel.${data.google_dns_managed_zone.zone.name}"]
    path_matcher = "allpaths"
  }

  path_matcher {
    name            = "allpaths"
    default_service = google_compute_backend_service.api.self_link

    path_rule {
      paths   = ["/v1/*"]
      service = google_compute_backend_service.api.self_link
    }
  }

}

resource "google_compute_global_forwarding_rule" "rule" {
  name                  = "api-forwarding-rule-${var.env}"
  port_range            = "443"
  load_balancing_scheme = "EXTERNAL_MANAGED"
  ip_protocol           = "TCP"
  target                = google_compute_target_https_proxy.api.id
  depends_on            = [google_compute_subnetwork.proxy_subnet, google_compute_global_forwarding_rule.rule]
}

# allow all access from IAP and health check ranges
resource "google_compute_firewall" "fw_iap" {
  name          = "l7-ilb-fw-allow-iap-hc-${var.env}"
  direction     = "INGRESS"
  network       = google_compute_network.network.id
  source_ranges = ["130.211.0.0/22", "35.191.0.0/16", "35.235.240.0/20"]
  allow {
    protocol = "tcp"
  }
}

# allow http from proxy subnet to backends
resource "google_compute_firewall" "fw_ilb_to_backends" {
  name          = "l7-ilb-fw-allow-lb-to-backends-${var.env}"
  direction     = "INGRESS"
  network       = google_compute_network.network.id
  source_ranges = ["10.0.0.0/24"]
  target_tags   = ["http-server"]
  allow {
    protocol = "tcp"
    ports    = ["8000"]
  }
}
