# カスタムドメインの DNS（Cloud Domains 登録時に自動作成されたゾーンを import）。
# apex の A/AAAA は Cloud Run domain mapping が要求するレコード（run_edge.tf と対）。
resource "google_dns_managed_zone" "hoiku_agent_app" {
  name        = "hoiku-agent-app"
  dns_name    = "${var.domain}."
  description = "ドメインの DNS ゾーン: ${var.domain}"

  dnssec_config {
    state = "on"
  }
}

resource "google_dns_record_set" "apex_a" {
  name         = "${var.domain}."
  type         = "A"
  ttl          = 300
  managed_zone = google_dns_managed_zone.hoiku_agent_app.name
  rrdatas      = ["216.239.32.21", "216.239.34.21", "216.239.36.21", "216.239.38.21"]
}

resource "google_dns_record_set" "apex_aaaa" {
  name         = "${var.domain}."
  type         = "AAAA"
  ttl          = 300
  managed_zone = google_dns_managed_zone.hoiku_agent_app.name
  rrdatas      = ["2001:4860:4802:32::15", "2001:4860:4802:34::15", "2001:4860:4802:36::15", "2001:4860:4802:38::15"]
}
