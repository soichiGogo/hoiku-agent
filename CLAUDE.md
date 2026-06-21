概要・北極星・技術スタック・ディレクトリ構成・セットアップは @README.md を参照（重複させない）。
レイヤとコードの対応は @docs/architecture.md を参照。

# このプロジェクトの正（SSOT）と設計判断

- **企画・設計の正は Obsidian vault `google-cloud-hackathon` の `設計/プロダクト方針.md`**。これは
  リポジトリ外にあり Claude からは読めない。設計判断・仕様の根拠が要るときは推測で埋めず、
  `docs/architecture.md`（コード対応）を読むか、ユーザーに確認する。
- コード内の docstring は方針の節番号（§2＝型の保証 / §3＝二軸 / §4＝回す 等）を参照している。
  変更時はこの対応を崩さない。

# 開発コマンド（推測しないこと）

- 依存: `uv sync`（uv 推奨。`pip install -e ".[dev]"` でも可）
- ローカル実行: `adk run src/hoiku_agent`（CLI 対話）/ `adk web`（ブラウザ UI）。ADK は
  `agent.py` の `root_agent` を起点に探す。
- テスト: `pytest`（`testpaths=tests`, `pythonpath=src` は pyproject 済み）
- lint: `ruff check .` / `ruff format .`（line-length=100, target=py311）
- 認証/設定: `cp .env.example .env` → 記入 → `gcloud auth application-default login`

# アーキの心構え（3点）

1. **workflow層（型の保証）と agent層（中身の決定）を混ぜない**。書式・順序・必須項目の充足は
   `workflow/` で、内容の判断・不足情報の取得は `agents/` の `LlmAgent` で行う。
2. **作成AI（author）＋レビューAI（reviewer）の二軸**。レビューは作成段階に散らさず最終段階で
   一括評価し、OK が出るまで巡回する。
3. **育つ「文書作成指針」＝「回す」の本体**（`knowledge/文書作成指針.md`）。作成AIは作成前に参照し、
   レビューAIは評価基準に使う。追記（学習）は必ず HITL を挟む。

# コード規約（このリポジトリ固有）

- 各モジュール冒頭に `from __future__ import annotations` を置く（既存全モジュールに踏襲）。
- ADK エージェントは **`build_xxx()` ファクトリ関数**で構築して返す（`build_author_agent` /
  `build_review_agent` / `build_document_pipeline`）。モジュールトップレベルでインスタンス化しない
  （例外は ADK の起点である `agent.py` の `root_agent` のみ）。
- エージェント間の受け渡しは ADK の **`output_key` → `state[...]`** で行う（`state["draft"]` /
  `state["review"]`）。独自のグローバル変数で渡さない。
- スキーマは `schemas/` の pydantic モデルに集約（`DocumentSpec` / `ReviewCriteria` /
  `ReviewFinding`）。同じ関心事を別所で二重定義しない。
- docstring・コメント・LLM プロンプトは日本語。

# 現状＝設計フェーズ（雛形）

多くのツール・終了条件は `TODO(設計)` のスタブ。**スタブを場当たりで埋めない**。実装着手時は
`docs/architecture.md`「未実装の要所」とプロダクト方針を確認し、既存レイヤ構造に沿って入れる。
主な未実装: レビュー APPROVED 判定での Loop 早期終了 / author↔review 間の HITL 関門 /
Vertex RAG corpus 接続 / 出力フォーマットの最終バリデーション。

# IMPORTANT: 個人情報・秘密の取り扱い

- **実データ（個人情報を含みうる保育書類・園データ）は絶対にコミットしない**。`data/`・
  `samples/private/`・`knowledge/保育所保育指針/*` は `.gitignore` 済み。新たな実データ置き場を
  作るときは先に gitignore する。
- `.env`・サービスアカウント鍵（`*-key.json` 等）はコミットしない（gitignore 済み）。
- 生成書類に**子ども・保護者の個人名を書かない**（仮名・属性で表す）。文書作成指針の共通ルール。

# ブランチ・コミット・PR

グローバル CLAUDE.md のブランチ戦略・コミット/PR 規約に従う（ここでは再定義しない）。
