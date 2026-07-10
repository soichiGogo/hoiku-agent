terraform {
  required_version = ">= 1.5"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = ">= 6.0, < 8.0"
    }
    google-beta = {
      source  = "hashicorp/google-beta"
      version = ">= 6.0, < 8.0"
    }
  }

  # state は専用 GCS バケット（bootstrap で作成・infra/README.md）。backend 設定は変数不可のため直値。
  backend "gcs" {
    bucket = "hoiku-agent-hack-2026-tfstate"
    prefix = "infra"
  }
}

# add_terraform_attribution_label=false＝既存リソースへ goog-terraform-provisioned ラベルを付けない
# （import 時の不要な in-place 更新＝ラベル churn を避ける）。
provider "google" {
  project                         = var.project_id
  region                          = var.region
  add_terraform_attribution_label = false
}

provider "google-beta" {
  project                         = var.project_id
  region                          = var.region
  add_terraform_attribution_label = false
}
