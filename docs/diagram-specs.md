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
2. **Google Sign-In**: 本人確認とアプリ内セッションの入口。
3. **Google Cloud 境界**: Cloud Run を含む本番システム全体の包含範囲。
4. **Cloud Run / HOIKUAGENT**: 保育士向け UI、API、AI エージェントを稼働するアプリケーション実体。
5. **Vertex AI**: Gemini、RAG Engine、Memory Bank を内包する AI 基盤。
6. **Cloud SQL**: 園児、クラス、書類、指針、利用枠を保存するデータ基盤。
7. **Cloud Logging / Trace**: 構造化ログとエージェント実行軌跡。
8. **Artifact Registry / GitHub Actions**: コンテナイメージと WIF による鍵レス CI/CD。

### 必須の接続

- 保育士 ↔ Cloud Run: `HTTPS`。
- Google Sign-In → Cloud Run: `認証`。
- Cloud Run ↔ Cloud SQL: `保存・参照`。
- Cloud Run → Gemini: `生成`。
- Cloud Run → RAG Engine: `検索`。
- Cloud Run ↔ Memory Bank: `参照・承認後書き戻し`。書き戻し条件は注記する。
- Cloud Run → Cloud Logging / Trace: `ログ・トレース`。
- GitHub Actions → Artifact Registry: `WIF・鍵レス認証`。Artifact Registry → Cloud Run: `デプロイ`。

### 禁止する表現

- Cloud Run や HOIKUAGENT を Google Cloud 境界の外に置かない。
- Gemini、RAG Engine、Memory Bank を Vertex AI 境界と無関係な同列サービスとして置かない。
- 作成 AI、レビュー AI、改善エージェントの内部フローをこの図に描かない。
- 生成 AI に製品名、矢印、依存関係、Google Cloud ロゴを描かせない。

### 画像パーツの出典

- Cloud Run、Cloud SQL、Vertex AI: Google Cloud 公式 Core product icons。
- Artifact Registry、Cloud Logging、Cloud Trace: Google Cloud 公式 Legacy console icons。
- 保育士: gpt-image-2 で文字・ロゴ・矢印を含まない素材として生成し、クロマキー除去後に透過 PNG 化。

## `agent-workflow.drawio` — なぜ AI エージェントか

### 一番伝えること

国の方針で決まっている「文書の成立」はワークフローで保証できる。一方、制度に一意の手順がない「子どもの姿から、ねらい・援助・評価への変換」に保育士の勘所と AI エージェントの価値がある。その勘所は改善エージェントで育つ。

### 必須の対比

| ワークフローで保証する領域 | AI エージェントが支援する領域 |
| --- | --- |
| 必須欄、年齢分岐、集積、順序、様式、承認ゲート | 必要情報の選択、RAG・履歴参照、不足時の質問、姿→ねらい・援助・評価の変換、レビュー指摘による再作成 |
| 担当＝harness | 担当＝作成 AI・レビュー AI |
| 文書として成立させる | 状況に合う中身を考える |

### レイアウト

1. **上段の対比**: 「国の方針・園の様式で決まっている領域」と「制度に一意の変換手順がない領域」を並べる。
2. **つくる流れ**: harness の準備 → 作成 AI → レビュー AI → harness の確定前検査 → 保育士の確認・編集・承認。
3. **育てる流れ**: 修正・評価 → 改善エージェント → 指針カード提案 → 保育士の決定 → 育つ指針 → 次の作成へ前置。

作成 AI の内部に「必要情報の判断」と「姿から中身への変換」を置くが、外枠は必ず **単一 LlmAgent** とし、別々の AI を直列に並べたように見せない。

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
