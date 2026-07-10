variable "project_id" {
  type        = string
  description = "GCP プロジェクト ID"
}

variable "project_number" {
  type        = string
  description = "GCP プロジェクト番号（WIF principalSet の組み立てに使う）"
}

variable "region" {
  type        = string
  description = "既定リージョン"
  default     = "us-central1"
}

variable "github_owner" {
  type        = string
  description = "GitHub オーナー（WIF attribute condition 用）"
}

variable "github_repo" {
  type        = string
  description = "GitHub リポジトリ owner/repo（WIF attribute condition / principalSet 用）"
}

variable "domain" {
  type        = string
  description = "配布 UI のカスタムドメイン（Cloud Run domain mapping）"
}
