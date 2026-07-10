# 書類アーカイブ＋育つ指針の Cloud SQL（PostgreSQL 16・Phase 1/2）。
# ユーザー(hoiku/postgres)は password が state ドリフトを生むため TF 管理外（README 参照）。
resource "google_sql_database_instance" "hoiku_archive" {
  name             = "hoiku-archive"
  database_version = "POSTGRES_16"
  region           = var.region

  # 本番でないため削除保護は無効（実 DB に合わせる）。誤 destroy を防ぐなら true へ。
  deletion_protection = false

  settings {
    tier                        = "db-f1-micro"
    edition                     = "ENTERPRISE"
    availability_type           = "ZONAL"
    activation_policy           = "ALWAYS"
    pricing_plan                = "PER_USE"
    deletion_protection_enabled = false

    backup_configuration {
      enabled = false
    }

    ip_configuration {
      ipv4_enabled = true
    }
  }
}

resource "google_sql_database" "hoiku" {
  name     = "hoiku"
  instance = google_sql_database_instance.hoiku_archive.name
}
