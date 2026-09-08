> 共通指示の正本は本 AGENTS.md。CLAUDE.md は @AGENTS.md の読み込み入口。詳細は指定された時点で参照し、旧入口へ本文を複製しない。

概要・北極星・技術スタック・ディレクトリ構成・セットアップは @README.md を参照（重複させない）。
レイヤとコードの対応は @docs/architecture.md を参照。

# このプロジェクトの正（SSOT）と設計判断

- **参照配線（2026-07-11・2026-07-12簡素化）**：書類ごとの参照方針は専用カード種別でなく、他の指針カードと同じ自然文の1枚（PolicyScope 別）として書く（例:「保育経過記録の作成では、対象期間の保育日誌と、前回までの保育経過記録すべてを参照する」）。author/reviewer は `fetch_reference` で seed 候補を agentic に取得し `reference_manifest` に実績を残す。固定 digest 注入と pipeline 常設 prep は使わない。seed API/state key/workspace 境界は不変。チェックボックス式の構造化トグルUI（旧 `reference_policy`/`ReferenceRule`）は撤去し、改善エージェントの提案→比較相談→即反映フローで育てる（UXの単純さを精度より優先＝ユーザー判断）。

- **最終的な正は Obsidian vault `google-cloud-hackathon` の `設計/プロダクト方針.md`（製品方針）と
  `設計/エージェント設計.md`（アーキ）**。リポジトリ外にあり Claude からは読めない。
- **リポジトリ内の設計参照は `docs/設計コンテキスト.md`（開発ハンドオフの凝縮版）→ `docs/architecture.md`
  （コード対応）の順に見る**。なお不明なら推測で埋めずユーザーに確認。両者が食い違ったら vault が正。
- コード内の docstring は設計コンテキストの節番号（§4＝アーキ全体像 / §5＝責務境界 / §6＝作成AI /
  §7＝レビューAI / §8＝改善エージェント / §9＝メモリ / §10＝スキーマ / §12＝eval / §19＝ヒアリング反映
  2026-07：保育経過記録＝L3 集積・全年齢化）を参照する。崩さない。
- **構造・規約を変えたら本 AGENTS.md と `docs/architecture.md` を同じ変更内で更新する**（規約と実態の乖離・
  リンク切れを防ぐ。改名・移動・SSOT の置き場変更は特に）。
- **README の図解は `docs/diagram-specs.md` で内容を定義し、同名の `.drawio` を編集可能な正本、`.png` を掲載用の
  派生成果物とする**。画像パーツは `docs/diagram-assets/` に分離し、製品アイコンは公式素材、生成 AI は文字・ロゴ・
  矢印を含まない固有イラストだけに使う。責務境界やデータフローを変えたら仕様・draw.io・PNG を同じ変更内で同期する。

# 開発コマンド（推測しないこと）

- 依存: `uv sync`（uv 推奨。`pip install -e ".[dev]"` でも可）
- ローカル実行: `adk run src/hoiku_agent`（CLI 対話）/ `adk web src`（開発 UI。agents dir＝`src/`・`/dev-ui/`）。
  **保育士向け配布 UI は `uvicorn server:app` → `http://localhost:8000/app/`**（日誌/月案/回す を1枚で・`web/`＝層A
  presentation。生成は ADK ネイティブ REST を直接駆動し自前 Runner は組まない＝§9。配布リンクは `.env` の
  Google Sign-In と LLM 利用枠で LLM を回す口を保護＝コスト/濫用対策。規約は `src/hoiku_agent/web/CLAUDE.md`）。
  本番/ローカル共通の入口は repo root の `server.py`（`get_fast_api_app`）＝`uvicorn server:app`。Memory Bank を
  使うときは `.env` に `AGENT_ENGINE_ID` を入れて `uvicorn server:app`（`config.memory_service_uri` が URI 化。
  未設定は InMemory 降格＝§9）。Memory Bank 本体は `uv run python scripts/provision_memory_bank.py --create` で
  作成・設定する（**生成モデル必須＋日本語/子の姿カスタマイズ**＝実機検証で確定。手順は `docs/ライブ実行手順.md`）。
  RAG corpus（静的ナレッジ）は `uv run python scripts/provision_rag_corpus.py --create` で作成・取り込み（ソースは
  `knowledge/保育所保育指針/`＝gitignore 済み。**新規 GCP は RagManagedDb を serverless へ REST 切替必須・埋め込みは
  日本語向け `text-multilingual-embedding-002`**＝実機検証で確定。`RAG_CORPUS` を `.env` に設定。手順は `docs/ライブ実行手順.md`）。
- テスト: `pytest`（`testpaths=tests`, `pythonpath=["src","."]`＝root の `server.py` も import 可・pyproject 済み）。harness の決定ロジックは
  `tests/test_harness/` で LLM 非依存に回る。結合（決定論E2E）は `tests/test_e2e/`＝`FakeLlm` 注入で
  日誌/月案パイプラインを creds 不要・LLM 非依存に通す（`/e2e` skill。pytest は dev extra ＝
  `uv run --extra dev pytest`）。eval ゲートの判定式は `tests/test_eval_gate.py`（LLM 非依存）/ ケース集合は
  `tests/test_eval_cases.py`。品質回帰の実採点は `RUN_LIVE_EVAL=1 uv run --extra eval pytest tests/test_eval.py`
  （層B・明示しない通常pytestではskip・要 `--extra eval` ＝
  `google-adk[eval]` ＋ LLM 資格情報）。**evalset JSON（`eval/cases/*.evalset.json`）に `ruff format` を当てない**（Python 扱いで壊れる）。
- lint: `ruff check .` / `ruff format .`（line-length=100, target=py311。`.` 指定は .py のみ整形）
- 認証/設定: `cp .env.example .env` → 記入 → `gcloud auth application-default login`
- 書類アーカイブ（任意・Phase 1）: `.env` に `DATABASE_URL`（Cloud SQL / ローカル Postgres）→
  `uv run alembic upgrade head`（スキーマ適用＝`migrations/`）。未設定は降格＝永続化なし・seed はサンプル
  （手順・Cloud SQL 作成は `docs/ライブ実行手順.md`）。
- 月案（doc_type=月案・L2 還流）は前月日誌を seed して回す専用入口 `uv run python scripts/run_monthly.py
  --child-id はるとくん --month 2026-07`（要 LLM 資格情報）。日誌は `adk web src`（doc_type 既定＝保育日誌）。
- クラス月案（doc_type=クラス月案・園の実様式＝月間指導計画・§18）は seed 3系統＋在籍児名簿（クラス児童の保育経過記録すべて＋
  それまでのクラス月案すべて＋経過記録に未反映の期間の日誌＋クラスの在籍児名簿〔class_roster＝0–2 個人目標の対象〕＝`record_store.class_monthly_seed_inputs` で合成・依存
  モデル 2026-07）で回す専用入口 `uv run python scripts/run_class_monthly.py --age-band 0-2 --month 2026-07`
  （要 LLM 資格情報）。個別月案が1児単位なのに対しクラス全体（＝年齢帯）単位で、区分×領域グリッド
  （養護2本柱＋教育5領域）＋0–2 の個人目標を書く。
- 保育経過記録（doc_type=保育経過記録・L3 還流＝期間日誌＋前回までの自己履歴の集積、対象期間は年度4期・各3か月固定）は専用入口 `uv run python
  scripts/run_child_record.py --child-id はるとくん --period 2026-04〜2026-06`（要 LLM 資格情報。期間日誌＋
  前回までの保育経過記録すべて〔作成対象の期は除外〕を seed）。
- 保育要録（doc_type=保育要録・L4 還流＝それまでの保育経過記録すべての集積・年長のみ・日誌は足さない）は専用入口
  `uv run python scripts/run_youroku.py --child-id はるとくん --fiscal-year 2026`（要 LLM 資格情報。
  それまでの保育経過記録すべて〔全期〕を seed。アーカイブ接続時は `list_child_record_entries` から取得・未接続はサンプル降格）。
- 配信（層A）: `Dockerfile`＝`uvicorn server:app`（Cloud Run・scale-to-zero・**非root/PID1 exec 形式で SIGTERM
  グレースフル**）。デプロイ＝`.github/workflows/deploy.yml`（WIF・**MUST ハードニング配線**＝`--max-instances`（`MAX_INSTANCES`
  var・既定4）/`--service-account`（`RUNTIME_SA` var＝最小権限・未設定は既定 SA 降格＋警告）/`DATABASE_URL` は
  Secret Manager 優先（`DATABASE_URL_SECRET` var・無ければ GH secret 平文降格）/**認証ポリシー再現**（`--no-iap`＋
  `--allow-unauthenticated` で案内画面を公開し、`GOOGLE_OAUTH_CLIENT_ID` var＋`SESSION_SECRET` secret を必須注入＝
  アプリ内 Google Sign-In session が `/app/`・API を fail-closed 保護）/
  **env 保全**（`--set-env-vars` は全置換ゆえ `MODEL_LOCATION` を明示管理し再デプロイで落とさない）/
  **DB migration 自動適用**（`CLOUDSQL_INSTANCE` var 設定時、deploy の**前**に Cloud SQL Auth Proxy 経由で `alembic upgrade head`
  を当てコードとスキーマを同じ deploy で前進させる＝migration drift の再発防止。additive/expand 前提・失敗時は deploy 中止。
  前提＝`DEPLOY_SA` に `roles/cloudsql.client`＋DB URL secret への `roles/secretmanager.secretAccessor`。手動 `alembic upgrade head`
  は初回セットアップ／破壊的変更時の fallback）。GCP 側の一度きり設定は `docs/ライブ実行手順.md`「本番運用ハードニング」。
  **dev は WIF 有効化済み＝main push で自動デプロイ**）/ eval ゲートCI＝`.github/workflows/eval-gate.yml`
  （関連PR/週次/手動・専用 `EVAL_SA`＝`eval-runner`・strict fail-closed・要 WIF+creds）。
- インフラ（IaC・基盤）: `infra/`＝**Terraform でプラットフォーム基盤を宣言化**（API 有効化/SA・IAM/WIF・Cloud SQL・
  Secret の器・DNS・Cloud Run ドメインマッピング・Artifact Registry）。**Cloud Run サービス本体（image/env/revision）は
  `deploy.yml` が所有＝Terraform は import/所有しない**（`gcloud run deploy` と衝突させない境界）。CI＝
  `.github/workflows/terraform.yml`（PR=plan / main=apply を Environment `infra-prod` の**手動承認**でゲート・WIF で
  専用 `tf-admin` SA を借用）。**スコープ外（理由つき・`infra/README.md`）**＝請求予算（billing 権限を CI に渡さない）/
  IAP 有効化・メンバー（直接 IAP のまま）/ Cloud SQL ユーザー・パスワード / Secret の値 / RAG corpus・Memory Bank
  （TF 非対応＝`scripts/provision_*.py` が正）。初回のみローカル owner で bootstrap（state バケット＋`terraform apply`）
  ＝手順は `infra/README.md`（`docs/ライブ実行手順.md` は詳細/ fallback）。
- 可観測性: `src/hoiku_agent/logging_config.py`＝Cloud Run 向け構造化 JSON ログ（stdout 1行 JSON・severity・
  `X-Cloud-Trace-Context` 相関）。`server.py` 入口で `configure_logging()`＋`install_trace_middleware()`。
  Cloud Logging クライアントは手組みしない（マネージド昇格に委ねる）。ローカルは `K_SERVICE` 無しでテキスト降格（`LOG_FORMAT`/`LOG_LEVEL`）。
  **スパン＝ADK ネイティブの `trace_to_cloud`**（`server.py` が `settings.trace_to_cloud`＝env `TRACE_TO_CLOUD` を中継・
  自前 OTel 手組みしない）：agent/LLM/ツール呼び出しの軌跡を Cloud Trace へ（deploy.yml が本番 `TRACE_TO_CLOUD=true` を注入・
  実行SAに `roles/cloudtrace.agent`）。既定 false＝ローカル/CI は送らない降格。
- 二階（改善エージェント）は **root_agent とは別エントリ・手動起動**（v0）。専用スクリプト
  `uv run python scripts/run_improver.py --diff "…" [--feedback "…"]` で起こす（要 LLM 資格情報）。
  document_pipeline には組み込まない。
- **ADK 探索の事実**: agents dir＝`src/`、agent package＝`hoiku_agent/`、`root_agent` は `agent.py` のみで
  トップレベル化、`__init__.py` の `from . import agent` を壊さない。`adk web` は `src/` を指して起動する
  （リポジトリ root で叩くと dropdown に出ない）。

# アーキ＝3責務（実装で混ぜてはいけない線。詳細は各層の AGENTS.md）

1. **harness/（決定的・型の保証）** — 必須欄・年齢分岐・順序・集積・**doc_type分岐（router）**・指針カードストア・
   **表記正規化（ひらがな表記DX＝`notation_store`）**・**様式テンプレート（本文レイアウトのデータ＝`template_store`。
   章立て・ラベル・出し分けを JSON に外出しし、テキスト整形（draft.py）・帳票PDF・編集フォームの3レンダラが共通で歩いて描く
   ＝§18 の園差をテンプレ編集で吸収・レイアウトの三重管理を解消・整形実体は harness）**。
   LLM を呼ばない。**決定ロジックの実体はここに1つだけ**。
   （文書作成指針の agent への提示は author/reviewer の InstructionProvider＝`agents/instructions.py` が harness の
   `render_for_doc` を prompt 冒頭へ注入＝薄い組み立て。決定ロジック実体は harness の policy_store／aggregate に1つ。）
   `tools/validate_fields.py`・`tools/write_draft.py` は これを呼ぶ**薄いラッパ**（二重実装しない）。表記の統一は
   soft な指針カードでなく決定的正規化（確定時に取りこぼしなく適用＝型/表記の保証）＝別の道具（線を混ぜない）。
   Memory 書き戻しは**保存済み現行版に対する保育士の明示承認＋型成立**でのみ
   `/api/records/approve` から発火する（`harness/memory_writeback.py` が事実欄だけを子ども別 fact 化。
   接続済みの失敗は承認を fail-closed、未接続は降格。同期済み版は migration 0013 で保持）。
2. **agents/（agentic・中身の決定）** — author（日誌）/ monthly_author（月案）/ child_record_author（保育経過記録）/
   nursery_record_author（保育要録）＝**単一 LlmAgent**（内部を多層化しない。巡回＝再作成は harness の
   `build_authoring_loop` が [作成→レビュー→ゲート] に包んで担う＝NEEDS_REVISION で author が指摘点を再作成）、
   reviewer＝Evaluator（日誌/月案/保育経過記録/保育要録で共用・開示前提の表現観点を含む）。巡回制御・早期終了は harness 側。
3. **improver/（二階・回す）** — 修正メモ→育つ指針カードの追加/改訂または参照資料の既定変更を自走提案。**既存カードとの意味的競合を
   精査し、競合は保育士に比較相談、保育士の決定で即反映**（add/supersede。番人＝意味的競合精査＋保育士決定）。
   指針編集の決定的実体は harness/policy_store（「回した証拠」＝カード内蔵の変更履歴）。**eval は取り込みから外す**
   （CI の品質回帰として温存＝decouple）。

**メモリ3分類**: 子ども長期記憶＝Agent Engine Memory Bank（repo外）／ 育つ指針＝構造化カード
（runtime の正は `DATABASE_URL` 設定時 **Cloud SQL の policy_books 1行（book 丸ごと JSONB・version 楽観ロック）**
＝書類アーカイブと同じ DB へ統合（Phase 2・GCS は廃止）。未設定はローカル `knowledge/文書作成指針.json`＝
git はシード（DB 行不在時のフォールバックシードも兼ねる）。**agent への提示＝author/reviewer の InstructionProvider
（`agents/instructions.py`）が作る書類（doc_type）の scope に合わせ共通＋当該書類の勘所を prompt 冒頭へ前置注入**
（作成/レビューAI は自発的な read_policy 呼び出しでなく与件として動く。§5＝決定的に用意できる指針は harness の
`render_for_doc` を注入する。旧 read_policy ツールは撤去）、improver が保育士決定で即反映）／
静的知識＝Vertex RAG（`knowledge/保育所保育指針/` は gitignore のRAGソース）。
「全部ファイルベース」にしない。なお **表記ルール辞書（ひらがな表記DX＝`notation_store`・`notation_books` 1行・
migration 0004・未設定はローカル `knowledge/表記ルール.json` シード）** は "メモリ" ではなく決定的な表記統一の
辞書（保育士が編集・harness が確定時に適用）＝育つ指針カードとは役割が別（agentic な勘所 vs 決定的な表記）。

# コード規約（このリポジトリ固有）

- 各モジュール冒頭に `from __future__ import annotations` を置く。
- ADK エージェントは **`build_xxx()` ファクトリ関数**で構築して返す（`build_monthly_author_agent` /
  `build_class_monthly_author_agent` / `build_child_record_author_agent` /
  `build_nursery_record_author_agent` / `build_review_agent` / `build_improver_agent` /
  `build_proofreader_agent`（校正AI） / `build_upload_parser_agent`（取込抽出AI） /
  `build_monthly_pipeline` / `build_class_monthly_pipeline` /
  `build_child_record_pipeline` / `build_nursery_record_pipeline` / `build_root_agent`）。
  トップレベルでインスタンス化しない（例外は `agent.py` の `root_agent` のみ）。
  **保育日誌の AI 生成は退役**したため `build_author_agent` / `build_document_pipeline` は無い（日誌は手入力＝web）。
- エージェント間の受け渡しは **`output_key` → `state[...]`**（`state["draft"]` / `state["review"]`）。
  独自グローバルで渡さない。
- スキーマは `schemas/` の pydantic モデルに集約。同じ関心事を別所で二重定義しない。
- instruction（プロンプト）は各層の `prompts.py` に分離する。
- docstring・コメント・LLM プロンプトは日本語。

# 実装着手前の確認

[エージェント実装状況.md](エージェント実装状況.md) を必ず読み、対象の現状と制約を確認する。

# IMPORTANT: 個人情報・秘密の取り扱い

- **実データ（個人情報を含みうる保育書類・園データ）は絶対にコミットしない**。`data/`・`samples/private/`・
  `knowledge/保育所保育指針/*` は gitignore 済み。新たな実データ置き場は先に gitignore する。
- `.env`・サービスアカウント鍵（`*-key.json` 等）はコミットしない（gitignore 済み）。
- **生成書類・eval ケースに子ども・保護者の実名を書かない**（仮名・属性で表す＝架空の子のみ）。
  eval seed／月案 seed の子どもは現場の日誌に寄せた**実在しない仮名の固定ロスター**（下の名前＋ちゃん/くん）を使い、
  `tests/test_eval_cases.py` の allowlist で機械的に担保する（記号名「架空児A」には戻さない）。
- 補足: CLAUDE.md は強制でなく文脈。PII 非コミットを確実化するなら `PreToolUse` hook が本筋（将来 `.claude/` で）。

# ブランチ・コミット・PR

グローバル CLAUDE.md のブランチ戦略・コミット/PR 規約に従う（ここでは再定義しない）。

## Codex 固有の自動公開フロー

このプロジェクトでは、グローバル規約のうち「push・PR 作成はユーザー確認後」とする部分を意図的な例外として扱う。
ユーザーから変更実装を依頼された場合、作業ブランチ上で次を確認なしに自動実行してよい。

1. テスト・lint・必要な検証を実行する
2. 意味的なまとまりごとに日本語のコミットを作成する
3. 作業ブランチをリモートへ push する
4. PR を作成する（PR タイトル・本文は日本語。生成ツール由来の署名・宣伝行は付けない）

main への直接 push、main への merge、既存 PR の承認・merge は自動実行しない。PR 作成後は、URL と検証結果を報告して停止する。
未コミット変更、テスト失敗、認証不足、競合、または対象範囲が不明な場合は、無理に公開せず停止して状況を報告する。

## Codex 固有のマージ後の整理

ユーザーが PR を merge したことを報告した場合に限り、次の後処理を自動実行してよい。

1. リモートを fetch し、対象 PR と作業ブランチが実際に merge 済みであることを確認する
2. merge 済みの作業ブランチ、対応するローカル worktree、不要な remote-tracking ref を整理する
3. primary checkout の統合ブランチを更新する
4. `git status`、worktree 一覧、残存ブランチを確認し、結果を報告する

ただし、未コミット変更、未 push のコミット、未 merge、同名ブランチの別用途、または削除対象を安全に特定できない状態では、ブランチや worktree を削除しない。削除せずに状況を報告して判断を仰ぐ。
