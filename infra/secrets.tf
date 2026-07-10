# DB 接続 URL のシークレット（器のみ）。値(version)は TF 管理外＝機密を state に載せない。
# 値の投入は手動 / CI の外（gcloud secrets versions add）。参照付与は iam.tf。
resource "google_secret_manager_secret" "database_url" {
  secret_id = "hoiku-database-url"

  replication {
    auto {}
  }
}
