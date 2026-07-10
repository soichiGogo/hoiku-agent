# 稼働中リソースを無停止で state へ採り込む import ブロック（TF 1.5+）。
# API 有効化(google_project_service)は enable が冪等なので import せず apply が no-op で adopt する。
# tf-admin SA とその IAM/WIF は新規作成（import しない）。

# --- サービスアカウント ---
import {
  to = google_service_account.hoiku_run
  id = "projects/hoiku-agent-hack-2026/serviceAccounts/hoiku-run@hoiku-agent-hack-2026.iam.gserviceaccount.com"
}
import {
  to = google_service_account.github_deployer
  id = "projects/hoiku-agent-hack-2026/serviceAccounts/github-deployer@hoiku-agent-hack-2026.iam.gserviceaccount.com"
}

# --- project IAM（hoiku-run） ---
import {
  to = google_project_iam_member.hoiku_run["roles/aiplatform.user"]
  id = "hoiku-agent-hack-2026 roles/aiplatform.user serviceAccount:hoiku-run@hoiku-agent-hack-2026.iam.gserviceaccount.com"
}
import {
  to = google_project_iam_member.hoiku_run["roles/cloudsql.client"]
  id = "hoiku-agent-hack-2026 roles/cloudsql.client serviceAccount:hoiku-run@hoiku-agent-hack-2026.iam.gserviceaccount.com"
}
import {
  to = google_project_iam_member.hoiku_run["roles/cloudtrace.agent"]
  id = "hoiku-agent-hack-2026 roles/cloudtrace.agent serviceAccount:hoiku-run@hoiku-agent-hack-2026.iam.gserviceaccount.com"
}

# --- project IAM（github-deployer） ---
import {
  to = google_project_iam_member.github_deployer["roles/artifactregistry.writer"]
  id = "hoiku-agent-hack-2026 roles/artifactregistry.writer serviceAccount:github-deployer@hoiku-agent-hack-2026.iam.gserviceaccount.com"
}
import {
  to = google_project_iam_member.github_deployer["roles/cloudbuild.builds.editor"]
  id = "hoiku-agent-hack-2026 roles/cloudbuild.builds.editor serviceAccount:github-deployer@hoiku-agent-hack-2026.iam.gserviceaccount.com"
}
import {
  to = google_project_iam_member.github_deployer["roles/cloudsql.client"]
  id = "hoiku-agent-hack-2026 roles/cloudsql.client serviceAccount:github-deployer@hoiku-agent-hack-2026.iam.gserviceaccount.com"
}
import {
  to = google_project_iam_member.github_deployer["roles/run.admin"]
  id = "hoiku-agent-hack-2026 roles/run.admin serviceAccount:github-deployer@hoiku-agent-hack-2026.iam.gserviceaccount.com"
}
import {
  to = google_project_iam_member.github_deployer["roles/storage.admin"]
  id = "hoiku-agent-hack-2026 roles/storage.admin serviceAccount:github-deployer@hoiku-agent-hack-2026.iam.gserviceaccount.com"
}

# --- SA レベル IAM ---
import {
  to = google_service_account_iam_member.deployer_actas_runtime
  id = "projects/hoiku-agent-hack-2026/serviceAccounts/hoiku-run@hoiku-agent-hack-2026.iam.gserviceaccount.com roles/iam.serviceAccountUser serviceAccount:github-deployer@hoiku-agent-hack-2026.iam.gserviceaccount.com"
}
import {
  to = google_service_account_iam_member.deployer_wif
  id = "projects/hoiku-agent-hack-2026/serviceAccounts/github-deployer@hoiku-agent-hack-2026.iam.gserviceaccount.com roles/iam.workloadIdentityUser principalSet://iam.googleapis.com/projects/412724895317/locations/global/workloadIdentityPools/github/attribute.repository/soichiGogo/hoiku-agent"
}

# --- secret レベル IAM（secretAccessor） ---
import {
  to = google_secret_manager_secret_iam_member.database_url_accessor["serviceAccount:hoiku-run@hoiku-agent-hack-2026.iam.gserviceaccount.com"]
  id = "projects/hoiku-agent-hack-2026/secrets/hoiku-database-url roles/secretmanager.secretAccessor serviceAccount:hoiku-run@hoiku-agent-hack-2026.iam.gserviceaccount.com"
}
import {
  to = google_secret_manager_secret_iam_member.database_url_accessor["serviceAccount:github-deployer@hoiku-agent-hack-2026.iam.gserviceaccount.com"]
  id = "projects/hoiku-agent-hack-2026/secrets/hoiku-database-url roles/secretmanager.secretAccessor serviceAccount:github-deployer@hoiku-agent-hack-2026.iam.gserviceaccount.com"
}

# --- WIF ---
import {
  to = google_iam_workload_identity_pool.github
  id = "projects/hoiku-agent-hack-2026/locations/global/workloadIdentityPools/github"
}
import {
  to = google_iam_workload_identity_pool_provider.github
  id = "projects/hoiku-agent-hack-2026/locations/global/workloadIdentityPools/github/providers/github"
}

# --- Cloud SQL ---
import {
  to = google_sql_database_instance.hoiku_archive
  id = "hoiku-agent-hack-2026/hoiku-archive"
}
import {
  to = google_sql_database.hoiku
  id = "hoiku-agent-hack-2026/hoiku-archive/hoiku"
}

# --- Secret（器） ---
import {
  to = google_secret_manager_secret.database_url
  id = "projects/hoiku-agent-hack-2026/secrets/hoiku-database-url"
}

# --- DNS ---
import {
  to = google_dns_managed_zone.hoiku_agent_app
  id = "hoiku-agent-hack-2026/hoiku-agent-app"
}
import {
  to = google_dns_record_set.apex_a
  id = "hoiku-agent-hack-2026/hoiku-agent-app/hoiku-agent.app./A"
}
import {
  to = google_dns_record_set.apex_aaaa
  id = "hoiku-agent-hack-2026/hoiku-agent-app/hoiku-agent.app./AAAA"
}

# --- Cloud Run domain mapping ---
import {
  to = google_cloud_run_domain_mapping.app
  id = "us-central1/hoiku-agent.app"
}

# --- Artifact Registry ---
import {
  to = google_artifact_registry_repository.cloud_run_source_deploy
  id = "projects/hoiku-agent-hack-2026/locations/us-central1/repositories/cloud-run-source-deploy"
}
