# サービスアカウント：hoiku-run（実行）/ github-deployer（CD）は既存＝import、
# eval-runner（層B実採点）/ tf-admin（IaC）は Terraform 管理。
resource "google_service_account" "hoiku_run" {
  account_id   = "hoiku-run"
  display_name = "hoiku-agent Cloud Run runtime"
}

resource "google_service_account" "github_deployer" {
  account_id   = "github-deployer"
  display_name = "GitHub Actions deployer (Cloud Run CD)"
}

resource "google_service_account" "eval_runner" {
  account_id   = "eval-runner"
  display_name = "GitHub Actions eval runner (Vertex AI only)"
}

resource "google_service_account" "tf_admin" {
  account_id   = "tf-admin"
  display_name = "Terraform admin (IaC)"
}

locals {
  # 実行 SA（最小権限）：Vertex/Gemini・Cloud SQL 接続・Cloud Trace 書込。
  hoiku_run_roles = [
    "roles/aiplatform.user",
    "roles/cloudsql.client",
    "roles/cloudtrace.agent",
  ]
  # CD SA：Cloud Build→AR→Cloud Run デプロイ、DB migration の Cloud SQL 接続、ソース staging(GCS)。
  github_deployer_roles = [
    "roles/artifactregistry.writer",
    "roles/cloudbuild.builds.editor",
    "roles/cloudsql.client",
    "roles/run.admin",
    "roles/storage.admin",
  ]
  # eval SA：エージェント生成＋Gemini judge の Vertex 推論だけ。CD/DB/Secret 権限を混ぜない。
  eval_runner_roles = [
    "roles/aiplatform.user",
  ]
  # tf-admin：フル基盤を管理する project スコープの admin 最小セット
  # （billing budget はスコープ外＝billing-account 権限を CI SA に渡さない。budget は手動運用）。
  tf_admin_roles = [
    "roles/iam.serviceAccountAdmin",
    "roles/resourcemanager.projectIamAdmin",
    "roles/iam.workloadIdentityPoolAdmin",
    "roles/cloudsql.admin",
    "roles/secretmanager.admin",
    "roles/dns.admin",
    "roles/artifactregistry.admin",
    "roles/serviceusage.serviceUsageAdmin",
    "roles/run.admin",
    "roles/iam.serviceAccountUser",
    "roles/storage.admin",
  ]

  # 自リポの GitHub Actions を表す WIF principalSet（SA 借用の許可先）。
  wif_repo_principal = "principalSet://iam.googleapis.com/projects/${var.project_number}/locations/global/workloadIdentityPools/${google_iam_workload_identity_pool.github.workload_identity_pool_id}/attribute.repository/${var.github_repo}"
}

resource "google_project_iam_member" "hoiku_run" {
  for_each = toset(local.hoiku_run_roles)
  project  = var.project_id
  role     = each.value
  member   = "serviceAccount:${google_service_account.hoiku_run.email}"
}

resource "google_project_iam_member" "github_deployer" {
  for_each = toset(local.github_deployer_roles)
  project  = var.project_id
  role     = each.value
  member   = "serviceAccount:${google_service_account.github_deployer.email}"
}

resource "google_project_iam_member" "eval_runner" {
  for_each = toset(local.eval_runner_roles)
  project  = var.project_id
  role     = each.value
  member   = "serviceAccount:${google_service_account.eval_runner.email}"
}

resource "google_project_iam_member" "tf_admin" {
  for_each = toset(local.tf_admin_roles)
  project  = var.project_id
  role     = each.value
  member   = "serviceAccount:${google_service_account.tf_admin.email}"
}

# github-deployer が hoiku-run を actAs（gcloud run deploy --service-account に必須）。
resource "google_service_account_iam_member" "deployer_actas_runtime" {
  service_account_id = google_service_account.hoiku_run.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.github_deployer.email}"
}

# WIF：自リポの Actions が CD SA / eval SA / tf-admin SA を借用（鍵レス）。
resource "google_service_account_iam_member" "deployer_wif" {
  service_account_id = google_service_account.github_deployer.name
  role               = "roles/iam.workloadIdentityUser"
  member             = local.wif_repo_principal
}

resource "google_service_account_iam_member" "tf_admin_wif" {
  service_account_id = google_service_account.tf_admin.name
  role               = "roles/iam.workloadIdentityUser"
  member             = local.wif_repo_principal
}

resource "google_service_account_iam_member" "eval_runner_wif" {
  service_account_id = google_service_account.eval_runner.name
  role               = "roles/iam.workloadIdentityUser"
  member             = local.wif_repo_principal
}

# DB URL secret の読み取り（実行 SA＋CD SA）。値(version)は TF 管理外＝機密を state に載せない。
resource "google_secret_manager_secret_iam_member" "database_url_accessor" {
  for_each = toset([
    "serviceAccount:${google_service_account.hoiku_run.email}",
    "serviceAccount:${google_service_account.github_deployer.email}",
  ])
  secret_id = google_secret_manager_secret.database_url.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = each.value
}
