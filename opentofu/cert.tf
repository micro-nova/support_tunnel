resource "google_certificate_manager_certificate" "default" {
  name = "api-${var.env}"
  managed {
    domains = [
      google_certificate_manager_dns_authorization.default.domain,
    ]
    dns_authorizations = [
      google_certificate_manager_dns_authorization.default.id,
    ]
  }
}

resource "google_certificate_manager_dns_authorization" "default" {
  name        = "support-tunnel"
  description = "The default dnss"
  domain      = "support-tunnel.${var.env}.${var.domain}"
}

resource "google_dns_record_set" "cname" {
  name         = google_certificate_manager_dns_authorization.default.dns_resource_record[0].name
  managed_zone = data.google_dns_managed_zone.zone.name
  type         = google_certificate_manager_dns_authorization.default.dns_resource_record[0].type
  ttl          = 300
  rrdatas      = [google_certificate_manager_dns_authorization.default.dns_resource_record[0].data]
}

resource "google_certificate_manager_certificate_map" "certificate_map" {
  name = "api-${var.env}"
}

resource "google_certificate_manager_certificate_map_entry" "default" {
  name         = "api-${var.env}"
  map          = google_certificate_manager_certificate_map.certificate_map.name
  certificates = [google_certificate_manager_certificate.default.id]
  matcher      = "PRIMARY"
}
