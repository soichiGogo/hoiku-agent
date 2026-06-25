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
- ローカル実行: `adk run src/hoiku_agent`（CLI 対話）/ `adk web src`（ブラウザ UI。agents dir＝`src/`）。
- テスト: `pytest`（`testpaths=tests`, `pythonpath=src` は pyproject 済み）。harness の決定ロジックは
  `tests/test_harness/` で LLM 非依存に回る。結合（決定論E2E）は `tests/test_e2e/`＝`FakeLlm` 注入で
  author→review→finalize を creds 不要・LLM 非依存に通す（`/e2e` skill。pytest は dev extra ＝
  `uv run --extra dev pytest`）。品質回帰は `pytest tests/test_eval.py`（層B・要 LLM）。
- lint: `ruff check .` / `ruff format .`（line-length=100, target=py311）
- 認証/設定: `cp .env.example .env` → 記入 → `gcloud auth application-default login`
- 二階（改善エージェント）は **root_agent とは別エントリ・手動起動**（v0）。専用スクリプト
  `uv run python scripts/run_improver.py --diff "…" [--feedback "…"]` で起こす（要 LLM 資格情報）。
  document_pipeline には組み込まない。
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

# 現状＝v0 実装済み（外部リソース接続は残課題）

決定的部分（harness）は実装＋テスト済みで、LLM/GCP 非依存で稼働する。実装状況の詳細は
`docs/architecture.md`「実装状況（v0）と残課題」を正とする（ここでは要点のみ・二重管理しない）。

- **実装済み**: レビュー APPROVED 早期終了（`harness/pipeline.py` の `ApprovalGate`/`is_approved`）/
  確定処理（`harness/finalize.py`＋`FinalizeAgent`：DiaryEntry JSON 復元→validate→write）/
  HITL（`ask_caregiver`＝`LongRunningFunctionTool`、確定段の `awaiting_caregiver_approval`）/
  `git_ops`（構造化編集の適用・competition 入力・branch/PR＝既定 dry_run）/ improver（propose＋競合検出・
  run_eval・open_pr）/ eval ゲート（`eval/run_gate.py`）/ ツールの降格（RAG/Memory 未設定でも落ちない）。
- **残課題（外部依存・コードは降格付きで配線済み）**: Vertex RAG corpus・Memory Bank の接続（config 設定で活性化）/
  Cloud Run デプロイ・実 Gemini の eval ゲートCI（WIF 認証・層A。決定論 CI＝`.github/workflows/ci.yml` は導入済み）/
  実様式での `write_draft` 確定（§18）/ 現場の修正差分による eval ケース拡充と 3軸 judge の ADK 接続（要 LLM 資格情報）。
- 新たにスタブを足すときは**場当たりで埋めない**（`docs/設計コンテキスト.md` の該当節＋既存レイヤに沿う）。
  決定的ロジックの実体は harness/eval に1つ・tools は薄いラッパ（§5）を崩さない。

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
