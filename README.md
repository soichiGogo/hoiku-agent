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
- **improver（回す・二階）**：先輩の勘所・園のルール・現場の修正を**育つ「文書作成指針」**へ吸収し続ける
  （＝「回す」の本体・`knowledge/文書作成指針.md`）。取り込みは HITL ＋ 評価ゲート経由。

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
├── agent.py            … ルートエージェント（root_agent）＝書類作成パイプライン
├── config.py           … 設定（GCPプロジェクト・モデル等。.env から）
├── harness/            … ① 型の保証（決定的）：必須欄・年齢分岐・順序・集積・git適用
├── agents/             … ② 中身の決定（agentic）：作成AI / レビューAI（+ prompts.py）
├── improver/           … ③ 回す（二階・別エントリ）：修正差分→指針更新を自走提案
├── tools/              … 4–8個のプリミティブ（記録/指針/RAG/メモリ/HITL/harness薄ラッパ）
├── schemas/            … 書類スキーマ・年齢分岐・10の姿タグ（pydantic 集約）
knowledge/              … 育つ文書作成指針（git）＋ 保育所保育指針（RAGソース・gitignore）
eval/                   … 「回す」層B：評価セット（cases/）＋ 3軸 judge（judges/）
docs/                   … 設計コンテキスト.md（開発ハンドオフ）/ architecture.md（コード対応）
tests/                  … test_harness/（決定ロジック）/ test_eval.py（層B 統合）
```

## セットアップ

```bash
# 依存（uv 推奨。pip でも可）
uv sync            # or: pip install -e .

# GCP 認証 & 設定
cp .env.example .env   # PROJECT_ID 等を記入
gcloud auth application-default login

# ローカル実行（ADK CLI）
adk run src/hoiku_agent      # CLI 対話
adk web                      # ブラウザ UI
```
