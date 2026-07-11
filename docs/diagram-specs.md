# README 図解仕様

README の図は、見栄えよりも設計上の事実と更新可能性を優先する。`.drawio` を編集可能な正本、同名の `.png` を README 掲載用の派生成果物とする。

## ツールの役割分担

- **内容定義**: `docs/設計コンテキスト.md` と `docs/architecture.md` を根拠に、図の主張・要素・矢印・禁止事項を本書で固定する。
- **構造と文字**: draw.io で描く。日本語ラベル、矢印、責務境界、配置を決定的に保つ。
- **製品アイコン**: Google Cloud の公式アイコンを `docs/diagram-assets/` に置き、draw.io の独立した画像セルとして扱う。
- **画像生成 AI**: 文字・製品ロゴ・矢印を生成させず、保育士などプロジェクト固有の装飾イラストだけに使う。生成物は透過パーツにして `docs/diagram-assets/` に置く。
- **掲載用 PNG**: `.drawio` に画像パーツを自己完結形式で埋め込んでから書き出す。ラベル・包含関係・矢印は画像化せず、draw.io 上で手動調整可能に保つ。

## 共通ルール

- 16:9 の横長で、README の本文幅でも読める文字量に抑える。
- 色は役割を固定する。保育士＝橙、harness＝緑、agents＝紫、improver＝青、外部基盤＝灰。
- AI は下書きと提案を担い、最終判断は保育士が行うことを明示する。
- 保育日誌は保育士の手入力であり、作成 AI の経路に置かない。
- Memory Bank への書き戻しは「保育士の明示承認＋型成立」の場合だけとする。
- 育つ指針、表記ルール、子どもの長期記憶を同じものとして描かない。

## `system-architecture.drawio` — システム構成

### 一番伝えること

HOIKUAGENT が Google Cloud 上でどう配信・実行・保存・監視されるかを示す。エージェント内部の作成・レビュー・改善フローはこの図に持ち込まない。

### 必須要素

1. **保育士**: PC・スマートフォンから HTTPS で利用する外部アクター。
2. **Google Sign-In**: ID token による本人確認と、アプリ内セッションの入口。IAP ではない。
3. **Cloud DNS / 独自ドメイン**: DNSSEC、Cloud Run Domain Mapping、マネージド HTTPS 証明書を含む公開入口。
4. **Google Cloud 境界**: Cloud Run だけでなく、AI・データ・セキュリティ・配信基盤を含む本番システム全体の包含範囲。
5. **Cloud Run / HOIKUAGENT**: 保育士向け UI、API、AI エージェントを稼働するアプリケーション実体。scale-to-zero、専用 runtime SA、利用枠管理を示す。
6. **Vertex AI**: Gemini、RAG Engine、Agent Engine を内包する AI 基盤。Agent Engine は Memory Bank と ADK 共有セッションに使う。
7. **Cloud SQL**: ユーザー・園児・クラス・書類・指針・表記・様式・feedback・監査・削除依頼・利用枠を保存するデータ基盤。
8. **Secret Manager**: `DATABASE_URL` を Cloud Run とデプロイ前の schema 更新処理へ安全に注入する。
9. **Cloud Logging / Trace**: 構造化ログ、リクエスト相関、エージェント実行軌跡。
10. **GitHub Actions / WIF・IAM**: CI / CD・AI 評価・IaC を起動し、GitHub OIDC を Google Cloud の短期認証へ交換して用途別 SA を借用する。DB schema の更新はデプロイ前の処理として示し、独立した GCP リソースとして描かない。
11. **Cloud Build / Artifact Registry**: ソースからコンテナをビルドし、イメージを保存して Cloud Run へ配信する。
12. **Terraform / Cloud Storage**: IAM / WIF・Cloud SQL・Secret Manager・DNS・Artifact Registry を宣言管理し、GCS を Terraform state に使う。アプリデータは置かない。

### 必須の接続

- 保育士 → Cloud DNS / 独自ドメイン → Cloud Run: `HTTPS`。
- Google Sign-In → Cloud Run: `本人確認・アプリ内セッション`。
- Cloud Run ↔ Cloud SQL: `保存・参照`。
- Secret Manager → Cloud Run: `DB 接続情報`。
- Cloud Run → Vertex AI: `生成・検索`。
- Cloud Run ↔ Agent Engine / Memory Bank: `参照・承認後書き戻し`。書き戻し条件と共有セッション用途を注記する。
- GitHub Actions → WIF / IAM: `GitHub OIDC・鍵レス認証`。
- WIF / IAM → Cloud Build → Artifact Registry → Cloud Run: `build・push・デプロイ`。
- WIF / IAM → Terraform → Cloud Storage: `tf-admin SA・state`。

### 禁止する表現

- Cloud Run や HOIKUAGENT を Google Cloud 境界の外に置かない。
- Gemini、RAG Engine、Agent Engine を Vertex AI 境界と無関係な同列サービスとして置かない。
- 作成 AI、レビュー AI、改善エージェントの内部フローをこの図に描かない。
- IAP、VPC Connector、External Load Balancer を現行構成として描かない。
- WIF を Artifact Registry 固有の認証、Artifact Registry をビルド実行基盤として描かない。
- Cloud Storage を書類・指針・子どもの記憶の保存先として描かない。
- 生成 AI に製品名、矢印、依存関係、Google Cloud ロゴを描かせない。

### 画像パーツの出典

- Cloud Run、Cloud SQL、Vertex AI: Google Cloud 公式 Core product icons。
- Artifact Registry、Cloud Logging、Cloud Trace: Google Cloud 公式 Legacy console icons。
- 保育士: gpt-image-2 で文字・ロゴ・矢印を含まない素材として生成し、クロマキー除去後に透過 PNG 化。

## `agent-workflow.drawio` — HOIKUAGENT の仕組み

### 一番伝えること

国の方針で決まっている「文書の成立」はワークフローで保証できる。一方、制度に一意の手順がない「子どもの姿から、ねらい・援助・評価への変換」に保育士の勘所と AI エージェントの価値がある。その勘所は改善エージェントで育つ。

### 必須の対比

| ワークフローで保証する領域 | AI エージェントが支援する領域 |
| --- | --- |
| 必須項目欄、年齢分岐、書類の種類、順序、様式、表記、承認条件 | 必要情報の選択、指針・履歴参照、不足時の質問、姿→ねらい・援助・評価の変換、レビュー指摘による再作成（最大3回） |
| 担当＝harness | 担当＝作成 AI・レビュー AI |
| 文書として成立させる | 状況に合う中身を考える |

### レイアウト

1. **上段の対比**: 「国の方針・制度の様式で決まっている領域」と「制度に一意の変換手順がない領域」を並べる。
2. **つくる流れ**: harness が参照候補を安全に用意 → 作成 AI とレビュー AI が必要情報を参照 → 作成 AI が情報を統合して変換 → レビュー AI が参照実績も点検 → harness の確定前検査 → 保育士の確認・編集・承認 → 確定文書を保存。
3. **育てる流れ**: 図上は右から左へ、修正・評価 → 改善エージェント → 指針カード提案 → 保育士の決定 → 育つ指針。保育士からの入力線は右側、次の作成への還流線は左側に分け、交差させない。

作成 AI の上には、育つ指針・参照ポリシーと必要情報をまとめた参照パネルを置く。図上は「過去書類・名簿」「子どもの長期記憶」「保育所保育指針・保育所児童保育要録指針」「不足情報を保育士に確認」と日本語の役割だけを表示する。作成 AI とレビュー AI から参照線を結び、保育士の確定文書が保存される線も同じパネルへ結ぶ。

作成 AI の内部に「コンテキストの統合」と「姿から中身への変換」を置くが、外枠は必ず **単一 LlmAgent** とし、別々の AI を直列に並べたように見せない。

### 改善ループ

確定書類への修正・👍👎・ひとこと → 改善エージェントが再利用できる勘所かを判断 → 既存カードとの意味的競合を精査 → 指針カードを提案 → 保育士が決定 → 次の作成・レビューへ前置する。

### 禁止する表現

- AI が国のルールや必須項目を自由に決めるように見せない。
- AI が最終承認するように見せない。
- 改善エージェントが保育士の決定なしに指針を書き換えるように見せない。
- eval を改善エージェントの指針取り込みゲートとして描かない。
- Memory Bank と育つ指針を同じ記憶として描かない。
- 生成 AI に日本語ラベル、矢印、作成・レビュー・改善の依存関係を描かせない。

### 画像パーツ

- `child-observation.png`: gpt-image-2 で文字・矢印を含まない「積み木を積む子ども」の素材として生成し、透過 PNG 化。
- `caregiver.png`: システム構成図と共通の保育士素材。
- 上記以外のカード、ラベル、背景、矢印は draw.io ネイティブセルで作る。
