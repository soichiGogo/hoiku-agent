# hoiku-agent（保育士 書類作成支援エージェント）

> 作業リポジトリ名は仮。DevOps × AI Agent Hackathon 2026 提出プロダクトのコード本体。
> 企画・設計ドキュメントは別ワークスペース（Obsidian vault `google-cloud-hackathon`）の `設計/プロダクト方針.md` を正とする。

## これは何か

保育士の書類作成業務を支援する AI エージェント。価値の核（北極星）は次の一点：

> **「どんな文書にも対応できる」ではなく、保育士の勘所を吸収し、改善サイクルによる文書の高度化を通じて、保育士が手間をかけず子供と本気で向き合える環境を整備する。**

ハッカソンの主論点は ①**AIエージェントによる価値創出**（ワークフローでなくエージェントの必然）と ②**テーマ「回す」の具現化**（改善サイクル）。競合優位性・ビジネス価値は主論点ではない。

## 設計の骨子（`設計/プロダクト方針.md` より）

- **workflow × agentic ハイブリッド**：文書の"型"（書式・章立て・必須項目）は**ワークフロー層**で精度保証。中身の決定は**エージェント層**が不足情報を自分で取りに行く（Agentic RAG / Reflection）。
- **作成AI ＋ レビューAI の二軸**：作成 → 保育士OK → レビューがOKを出すまで巡回。
- **育つ「文書作成指針」**：先輩の勘所・園のルール・現場の修正を吸収して改善し続ける（＝「回す」の本体）。`knowledge/文書作成指針.md`。

## 技術スタック（`ナレッジ/AIエージェント構築ガイド.md` §13）

| 役割 | 採用 |
|------|------|
| エージェント実装 | **Google ADK**（Python, コードファースト） |
| LLM | **Gemini**（Vertex AI 経由 / 一部 Claude を Model Garden 経由で併用検討） |
| 独自ナレッジDB (B) | **Vertex RAG Engine / Vector Search**（保育所保育指針・10の姿） |
| 長期メモリ・評価・実行基盤 | **Agent Engine**（Memory Bank / 評価 / Runtime） |
| デプロイ | **Cloud Run**（scale-to-zero） |

## ディレクトリ構成

```
src/hoiku_agent/
├── agent.py            … ルートエージェント（root_agent）＝書類作成パイプライン
├── config.py           … 設定（GCPプロジェクト・モデル等。.env から）
├── workflow/           … 型の保証（ワークフロー層）
├── agents/             … 中身の決定（作成AI / レビューAI）
├── tools/              … ツール群（ナレッジ検索・指針参照・ルール参照・Web検索）
├── schemas/            … 書類要件・レビュー項目のスキーマ
knowledge/              … B独自DBの素体＋育つ文書作成指針
eval/                   … 「回す」層B：保育士の修正差分→評価セット
docs/architecture.md    … アーキ詳細（プロダクト方針のコード対応）
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
