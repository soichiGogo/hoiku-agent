# Cloud Run へのカスタムドメイン割当。サービス本体（image/env/revision）は CI(deploy.yml)所有＝
# ここでは route_name でサービス名を参照するだけ（TF はサービスを import/所有しない＝境界）。
# 認証ポリシー（IAP 無効化・アプリ内 Google Sign-In）は deploy.yml が所有する。
# ドメインマッピングは同じ Cloud Run サービスへ到達させるだけで、ここでは認証方式を管理しない。
resource "google_cloud_run_domain_mapping" "app" {
  provider = google-beta
  location = var.region
  name     = var.domain

  metadata {
    namespace = var.project_id
  }

  spec {
    certificate_mode = "AUTOMATIC"
    route_name       = "hoiku-agent"
  }

  # certificate_mode は import 時に API が空返しし、既定 AUTOMATIC との差が「置換」を強いる
  # （このベータリソースの既知の癖）。稼働中の HTTPS を壊さないよう当該属性の差分は無視する。
  lifecycle {
    ignore_changes = [spec[0].certificate_mode]
  }
}
