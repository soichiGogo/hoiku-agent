# hoiku-agent（保育士 書類作成支援エージェント）

> 作業リポジトリ名は仮。DevOps × AI Agent Hackathon 2026 提出プロダクトのコード本体。
> 企画・設計ドキュメントは別ワークスペース（Obsidian vault `google-cloud-hackathon`）の `設計/プロダクト方針.md` を正とする。

## これは何か

保育士の書類作成業務を支援する AI エージェント。価値の核（北極星）は次の一点：

> **「どんな文書にも対応できる」ではなく、保育士の勘所を吸収し、改善サイクルによる文書の高度化を通じて、保育士が手間をかけず子供と本気で向き合える環境を整備する。**

ハッカソンの主論点は ①**AIエージェントによる価値創出**（ワークフローでなくエージェントの必然）と ②**テーマ「回す」の具現化**（改善サイクル）。競合優位性・ビジネス価値は主論点ではない。

## 設計の骨子（`docs/設計コンテキスト.md` より）

3つの責務に素直に分離する（多層マルチエージェントにはしない）。

- **harness（型の保証・決定的）**：書式・章立て・必須項目の充足・年齢分岐・順序を**決定的なコード**で保証。
- **agents（中身の決定・agentic）**：作成AI（単一エージェント）が不足情報を自分で取りに行く（Agentic RAG）。
  **作成AI ＋ レビューAI の二軸**で、レビューがOKを出すまで巡回し最終確定は保育士（HITL）。
- **improver（回す・二階）**：先輩の勘所・園のルール・現場の修正を**育つ「文書作成指針」＝構造化カード**へ
  吸収し続ける（＝「回す」の本体・`knowledge/文書作成指針.json`）。既存カードとの**意味的競合**を精査し、
  競合は保育士に比較相談、**保育士の決定で即反映**（番人＝意味的競合精査＋保育士決定。eval は CI 専用に decouple）。

詳細は `docs/設計コンテキスト.md` / `docs/architecture.md`、各層の `CLAUDE.md` を参照。

## 技術スタック（`docs/設計コンテキスト.md` §11）

| 役割 | 採用 |
|------|------|
| エージェント実装 | **Google ADK**（Python, コードファースト） |
| LLM | **Gemini**（Vertex AI 経由 / 一部 Claude を Model Garden 経由で併用検討） |
| 独自ナレッジDB (B) | **Vertex RAG Engine / Vector Search**（保育所保育指針・10の姿） |
| 長期メモリ・評価・実行基盤 | **Agent Engine**（Memory Bank / 評価 / Runtime） |
| デプロイ | **Cloud Run**（scale-to-zero） |

## ディレクトリ構成

各ディレクトリの「Claude が何をするか」は当該 `CLAUDE.md`、レイヤ↔コードは `docs/architecture.md` を参照。

```
src/hoiku_agent/
├── agent.py            … ルートエージェント（root_agent）＝doc_type 分岐ルータ（日誌/月案/児童票/保育要録・既定 日誌）
├── config.py           … 設定（GCPプロジェクト・モデル等。.env から）
├── harness/            … ① 型の保証（決定的）：必須欄・年齢分岐（0–2/3–5＝全年齢）・順序・集積（L2/L3/L4）・doc_type分岐・指針カードストア（policy_store）・表記正規化（notation_store＝ひらがな表記DX）・書類アーカイブ（record_store＝Cloud SQL・確定書類/児童マスタ/監査証跡）
├── agents/             … ② 中身の決定（agentic）：作成AI（日誌/月案/児童票/保育要録）/ レビューAI（+ prompts.py）
├── improver/           … ③ 回す（二階・別エントリ）：修正メモ→指針カードを提案・意味的競合を精査・保育士決定で即反映
├── tools/              … 4–8個のプリミティブ（記録/指針/RAG/メモリ/HITL/harness薄ラッパ）
├── schemas/            … 書類スキーマ（日誌/月案/児童票/保育要録）・指針カード（policy）・年齢分岐・10の姿タグ（pydantic 集約）
├── web/                … 層A 配布UI（保育士 SPA /app/）：日誌/月案/児童票/保育要録は ADK REST 直駆動・園の帳票PDF出力（chohyo_pdf）・指針を育てる（improver）は SSE 中継・表記ルール辞書（notation.js＝/api/notation の CRUD）
knowledge/              … 育つ文書作成指針＝構造化カード（git・文書作成指針.json）＋ 保育所保育指針（RAGソース・gitignore）
eval/                   … 「回す」層B：評価セット（cases/）＋ 3軸 judge（judges/）＋ test_config.json / run_gate.py
docs/                   … 設計コンテキスト.md（開発ハンドオフ）/ architecture.md（コード対応）
migrations/             … 書類アーカイブ（record_store）の Alembic スキーマ移行（uv run alembic upgrade head）
tests/                  … test_harness/（決定ロジック）/ test_e2e/（結合）/ test_eval*.py（層B）
Dockerfile / .github/   … 配信（層A）：Cloud Run コンテナ ＋ CI（ci / deploy / eval-gate）
```

## セットアップ

```bash
# 依存（uv 推奨。pip でも可）
uv sync            # or: pip install -e .

# GCP 認証 & 設定
cp .env.example .env   # PROJECT_ID 等を記入
gcloud auth application-default login

# ローカル実行（ADK CLI）
adk run src/hoiku_agent      # CLI 対話（日誌＝既定 doc_type。月案/児童票は下の専用入口で seed）
adk web src                  # ブラウザ UI（agents dir = src/。root で叩くと dropdown に出ない）

# 月案（L2 還流・前月日誌を seed して回す専用入口）
uv run python scripts/run_monthly.py --child-id はるとくん --month 2026-07

# 児童票（L3 還流・期間日誌を seed して回す専用入口）
uv run python scripts/run_child_record.py --child-id はるとくん --period 2026-04〜2026-06

# 本番入口（Cloud Run と同じ）／配信
uvicorn server:app           # get_fast_api_app。AGENT_ENGINE_ID 未設定は InMemory 降格
# → 保育士UI（配布UI）= http://localhost:8000/app/（日誌/月案/回す を1枚で・ADK dev UI は /dev-ui/）
# 配布リンクで Gemini 課金を守るなら .env に DEMO_PASSCODE を設定（LLM を回す口のみ要パスコード）
# デプロイ＝Dockerfile（uvicorn server:app）＋ .github/workflows/deploy.yml（WIF・要 GCP 設定）
```

実 LLM で動かす詳細手順（Vertex AI / AI Studio APIキーの2経路・トラブルシュート）は
[`docs/ライブ実行手順.md`](docs/ライブ実行手順.md) を参照（`.env` はルートに置きそこから起動）。
