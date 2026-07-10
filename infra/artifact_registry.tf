# Cloud Build → Cloud Run の --source デプロイが使う DOCKER リポジトリ（CD が自動生成した実体を import）。
resource "google_artifact_registry_repository" "cloud_run_source_deploy" {
  location      = var.region
  repository_id = "cloud-run-source-deploy"
  format        = "DOCKER"
}
