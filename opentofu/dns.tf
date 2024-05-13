# This used to be a resource but destroying & recreating it during dev
# was painful.
data "google_dns_managed_zone" "zone" {
  name = var.env
}

resource "google_dns_record_set" "api" {
  name         = "support-tunnel.${data.google_dns_managed_zone.zone.dns_name}"
  type         = "A"
  ttl          = 300
  managed_zone = data.google_dns_managed_zone.zone.name

  rrdatas = [google_compute_global_forwarding_rule.rule.ip_address]
}
