# Workload Identity 連携（GitHub OIDC・鍵レス）。CD（deploy.yml）と IaC（terraform.yml）が共有。
resource "google_iam_workload_identity_pool" "github" {
  workload_identity_pool_id = "github"
  display_name              = "GitHub Actions"
}

resource "google_iam_workload_identity_pool_provider" "github" {
  workload_identity_pool_id          = google_iam_workload_identity_pool.github.workload_identity_pool_id
  workload_identity_pool_provider_id = "github"
  display_name                       = "GitHub OIDC"

  # 自リポ限定（他リポが pool へ入れない＝WIF ベストプラクティス）。
  attribute_condition = "assertion.repository_owner=='${var.github_owner}' && assertion.repository=='${var.github_repo}'"

  attribute_mapping = {
    "google.subject"             = "assertion.sub"
    "attribute.repository"       = "assertion.repository"
    "attribute.repository_owner" = "assertion.repository_owner"
  }

  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }
}
