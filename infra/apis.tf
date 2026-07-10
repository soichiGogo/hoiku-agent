# アプリ／基盤が使う API を curated 管理（有効化済みの全 API を網羅はしない）。
# disable_on_destroy=false＝TF から外しても API は無効化しない（他リソースの巻き添え停止を避ける）。
locals {
  services = [
    "run.googleapis.com",
    "sqladmin.googleapis.com",
    "secretmanager.googleapis.com",
    "dns.googleapis.com",
    "domains.googleapis.com",
    "iap.googleapis.com",
    "aiplatform.googleapis.com",
    "cloudtrace.googleapis.com",
    "artifactregistry.googleapis.com",
    "cloudbuild.googleapis.com",
    "iam.googleapis.com",
    "iamcredentials.googleapis.com",
    "sts.googleapis.com",
    "serviceusage.googleapis.com",
    "cloudresourcemanager.googleapis.com",
    "storage.googleapis.com",
    "logging.googleapis.com",
    "monitoring.googleapis.com",
  ]
}

resource "google_project_service" "apis" {
  for_each = toset(local.services)
  project  = var.project_id
  service  = each.value

  disable_on_destroy         = false
  disable_dependent_services = false
}
