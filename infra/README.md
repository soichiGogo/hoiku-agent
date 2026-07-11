# infra/ — プラットフォーム基盤の IaC（Terraform）

hoiku-agent の**動きの遅いプラットフォーム基盤**を Terraform で宣言化する。
**アプリのデプロイ（Cloud Run のイメージ/env/revision）は CI（`.github/workflows/deploy.yml`）が所有**し、
ここでは触らない（TF と `gcloud run deploy` を衝突させないための境界）。

## 所有権の境界
| 対象 | 所有 |
|---|---|
| API 有効化・SA/IAM（eval専用SAを含む）・WIF・Cloud SQL・Secret（器）・DNS・ドメインマッピング・Artifact Registry | **Terraform（この dir）** |
| Cloud Run サービス本体（image/env/revision）・DB migration・eval ゲート | **CI = `deploy.yml`** |

## スコープ外（意図的・理由つき）
- **請求予算（budget）**：管理には billing-account レベルの権限が要り、CI SA に渡したくない（最小権限）。
  既存の「hoiku-agent dev budget」は手動運用のまま（変更は稀・一行）。
- **IAP の有効化／アクセスメンバー**：直接 IAP はサービスに付いたまま全入口を保護する。TF で有効化フラグや
  メンバーを持つと検証が難しく事故りやすいので現状維持（手動）。
- **Cloud SQL のユーザー/パスワード**：`password` が state ドリフトを生むため管理外（`hoiku`/`postgres`）。
- **Secret の値（version）**：機密を state に載せないため器のみ管理。値は `gcloud secrets versions add`。
- **RAG corpus / Agent Engine Memory Bank**：Terraform リソースが無い。`scripts/provision_*.py` が正。

## bootstrap（一度きり・ローカル・owner 権限で）
CI が TF を回すには先に state バケットと tf-admin SA が要る。最初だけローカルで：

```bash
# 1) state 用 GCS バケット（バージョニング＋UBLA）
gcloud storage buckets create gs://hoiku-agent-hack-2026-tfstate \
  --project=hoiku-agent-hack-2026 --location=us-central1 \
  --uniform-bucket-level-access
gcloud storage buckets update gs://hoiku-agent-hack-2026-tfstate --versioning

# 2) init（gcs backend）＋ 既存を import しつつ tf-admin 等を作成
cd infra
terraform init
terraform plan     # 既存=No changes、tf-admin SA とその IAM/WIF だけが (create) を確認
terraform apply    # owner の ADC で実行＝tf-admin を作成し import を確定
```

`terraform apply` は ADC（`gcloud auth application-default login`）の owner 権限で走る。
以後の変更は CI（`terraform.yml`）が **tf-admin** を借用して回す。

## 日常運用（CI）
- PR：`terraform plan`（差分をレビュー。eval専用SA変更もここで確認）
- main マージ：`terraform apply`（GitHub Environment `infra-prod` の**手動承認**ゲート）
- 手元で試すときも `terraform plan` は読み取り主体（apply は避ける／owner のみ）

## import の考え方
`imports.tf` の import ブロックが稼働実体を state へ採り込む（インフラは作り直さない）。
`terraform plan` が **No changes（tf-admin 系の新規を除く）** になるまで `.tf` を実体へ合わせる＝
「現状を正しく写した」安全確認。import は一度取り込めば以後 no-op。
