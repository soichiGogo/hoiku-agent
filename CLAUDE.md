概要・北極星・技術スタック・ディレクトリ構成・セットアップは @README.md を参照（重複させない）。
レイヤとコードの対応は @docs/architecture.md を参照。

# このプロジェクトの正（SSOT）と設計判断

- **最終的な正は Obsidian vault `google-cloud-hackathon` の `設計/プロダクト方針.md`（製品方針）と
  `設計/エージェント設計.md`（アーキ）**。リポジトリ外にあり Claude からは読めない。
- **リポジトリ内の設計参照は `docs/設計コンテキスト.md`（開発ハンドオフの凝縮版）→ `docs/architecture.md`
  （コード対応）の順に見る**。なお不明なら推測で埋めずユーザーに確認。両者が食い違ったら vault が正。
- コード内の docstring は設計コンテキストの節番号（§4＝アーキ全体像 / §5＝責務境界 / §6＝作成AI /
  §7＝レビューAI / §8＝改善エージェント / §9＝メモリ / §10＝スキーマ / §12＝eval）を参照する。崩さない。
- **構造・規約を変えたら本 CLAUDE.md と `docs/architecture.md` を同じ変更内で更新する**（規約と実態の乖離・
  リンク切れを防ぐ。改名・移動・SSOT の置き場変更は特に）。

# 開発コマンド（推測しないこと）

- 依存: `uv sync`（uv 推奨。`pip install -e ".[dev]"` でも可）
- ローカル実行: `adk run src/hoiku_agent`（CLI 対話）/ `adk web`（ブラウザ UI）。
- テスト: `pytest`（`testpaths=tests`, `pythonpath=src` は pyproject 済み）。harness の決定ロジックは
  `tests/test_harness/` で LLM 非依存に回る。品質回帰は `pytest tests/test_eval.py`（層B）。
- lint: `ruff check .` / `ruff format .`（line-length=100, target=py311）
- 認証/設定: `cp .env.example .env` → 記入 → `gcloud auth application-default login`
- 二階（改善エージェント）は **root_agent とは別エントリ・手動起動**（v0）。`adk run` で improver を指定 or
  専用スクリプト。document_pipeline には組み込まない。
- **ADK 探索の事実**: agents dir＝`src/`、agent package＝`hoiku_agent/`、`root_agent` は `agent.py` のみで
  トップレベル化、`__init__.py` の `from . import agent` を壊さない。`adk web` は `src/` を指して起動する
  （リポジトリ root で叩くと dropdown に出ない）。

# アーキ＝3責務（実装で混ぜてはいけない線。詳細は各層の CLAUDE.md）

1. **harness/（決定的・型の保証）** — 必須欄・年齢分岐・順序・集積・git適用。LLM を呼ばない。
   **決定ロジックの実体はここに1つだけ**。`tools/validate_fields.py`・`tools/write_draft.py` はこれを呼ぶ
   **薄いラッパ**（二重実装しない）。
2. **agents/（agentic・中身の決定）** — author＝**単一 LlmAgent**（v0 で LoopAgent に包まない・多層化しない）、
   reviewer＝Evaluator。レビューは最終段で一括、巡回制御は harness 側。
3. **improver/（二階・回す）** — 修正差分→育つ指針の更新を自走提案。**HITL＋評価ゲート経由でのみ取り込む**
   （保育士OK ≠ マージOK）。git は harness/git_ops 経由。

**メモリ3分類**: 子ども長期記憶＝Agent Engine Memory Bank（repo外）／ 育つ指針＝git
`knowledge/文書作成指針.md`（agent は読み取り・HEAD 参照、improver が編集）／ 静的知識＝Vertex RAG
（`knowledge/保育所保育指針/` は gitignore のRAGソース）。「全部ファイルベース」にしない。

# コード規約（このリポジトリ固有）

- 各モジュール冒頭に `from __future__ import annotations` を置く。
- ADK エージェントは **`build_xxx()` ファクトリ関数**で構築して返す（`build_author_agent` /
  `build_review_agent` / `build_improver_agent` / `build_document_pipeline`）。トップレベルでインスタンス化
  しない（例外は `agent.py` の `root_agent` のみ）。
- エージェント間の受け渡しは **`output_key` → `state[...]`**（`state["draft"]` / `state["review"]`）。
  独自グローバルで渡さない。
- スキーマは `schemas/` の pydantic モデルに集約。同じ関心事を別所で二重定義しない。
- instruction（プロンプト）は各層の `prompts.py` に分離する。
- docstring・コメント・LLM プロンプトは日本語。

# 現状＝設計フェーズ（雛形）

多くのツール・終了条件は `TODO(設計)` のスタブ。**スタブを場当たりで埋めない**。実装着手時は
`docs/設計コンテキスト.md` の該当節と既存レイヤ構造に沿って入れる。主な未実装: レビュー APPROVED 判定での
Loop 早期終了 / HITL 関門（ask_caregiver の同期ツール）/ Vertex RAG・Memory Bank 接続 /
出力の最終 validation / git_ops（構造化編集の適用・PR）/ eval ゲートの判定。

# IMPORTANT: 個人情報・秘密の取り扱い

- **実データ（個人情報を含みうる保育書類・園データ）は絶対にコミットしない**。`data/`・`samples/private/`・
  `knowledge/保育所保育指針/*` は gitignore 済み。新たな実データ置き場は先に gitignore する。
- `.env`・サービスアカウント鍵（`*-key.json` 等）はコミットしない（gitignore 済み）。
- **生成書類・eval ケースに子ども・保護者の実名を書かない**（仮名・属性で表す＝架空児のみ）。
- 補足: CLAUDE.md は強制でなく文脈。PII 非コミットを確実化するなら `PreToolUse` hook が本筋（将来 `.claude/` で）。

# ブランチ・コミット・PR

グローバル CLAUDE.md のブランチ戦略・コミット/PR 規約に従う（ここでは再定義しない）。
**注意**: improver/harness が行う git/PR 操作は「プロダクト自身が育つ指針を回す」ための処理であり、
開発者（人）のブランチ運用とは別物。同じ「git/PR」語彙で混同しない。
