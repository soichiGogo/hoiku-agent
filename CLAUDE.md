概要・北極星・技術スタック・ディレクトリ構成・セットアップは @README.md を参照（重複させない）。
レイヤとコードの対応は @docs/architecture.md を参照。

# このプロジェクトの正（SSOT）と設計判断

- **参照配線（2026-07-11）**：`reference_policy` カードが書類ごとの既定 source を持つ。author/reviewer は `fetch_reference` で seed 候補を agentic に取得し `reference_manifest` に実績を残す。固定 digest 注入と pipeline 常設 prep は使わない。seed API/state key/workspace 境界は不変。

- **最終的な正は Obsidian vault `google-cloud-hackathon` の `設計/プロダクト方針.md`（製品方針）と
  `設計/エージェント設計.md`（アーキ）**。リポジトリ外にあり Claude からは読めない。
- **リポジトリ内の設計参照は `docs/設計コンテキスト.md`（開発ハンドオフの凝縮版）→ `docs/architecture.md`
  （コード対応）の順に見る**。なお不明なら推測で埋めずユーザーに確認。両者が食い違ったら vault が正。
- コード内の docstring は設計コンテキストの節番号（§4＝アーキ全体像 / §5＝責務境界 / §6＝作成AI /
  §7＝レビューAI / §8＝改善エージェント / §9＝メモリ / §10＝スキーマ / §12＝eval / §19＝ヒアリング反映
  2026-07：保育経過記録＝L3 集積・全年齢化）を参照する。崩さない。
- **構造・規約を変えたら本 CLAUDE.md と `docs/architecture.md` を同じ変更内で更新する**（規約と実態の乖離・
  リンク切れを防ぐ。改名・移動・SSOT の置き場変更は特に）。

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
- クラス月案（doc_type=クラス月案・園の実様式＝月間指導計画・§18）は seed 3系統（クラス児童の保育経過記録すべて＋
  それまでのクラス月案すべて＋経過記録に未反映の期間の日誌＝`record_store.class_monthly_seed_inputs` で合成・依存
  モデル 2026-07）で回す専用入口 `uv run python scripts/run_class_monthly.py --age-band 0-2 --month 2026-07`
  （要 LLM 資格情報）。個別月案が1児単位なのに対しクラス全体（＝年齢帯）単位で、区分×領域グリッド
  （養護2本柱＋教育5領域）＋0–2 の個人目標を書く。
- 保育経過記録（doc_type=保育経過記録・L3 還流＝期間日誌＋前回までの自己履歴の集積）は専用入口 `uv run python
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

# アーキ＝3責務（実装で混ぜてはいけない線。詳細は各層の CLAUDE.md）

1. **harness/（決定的・型の保証）** — 必須欄・年齢分岐・順序・集積・**doc_type分岐（router）**・指針カードストア・
   **表記正規化（ひらがな表記DX＝`notation_store`）**・**様式テンプレート（本文レイアウトのデータ＝`template_store`。
   章立て・ラベル・出し分けを JSON に外出しし、テキスト整形（draft.py）・帳票PDF・編集フォームの3レンダラが共通で歩いて描く
   ＝§18 の園差をテンプレ編集で吸収・レイアウトの三重管理を解消・整形実体は harness）**。
   LLM を呼ばない。**決定ロジックの実体はここに1つだけ**。
   （文書作成指針の agent への提示は author/reviewer の InstructionProvider＝`agents/instructions.py` が harness の
   `render_for_doc` を prompt 冒頭へ注入＝薄い組み立て。決定ロジック実体は harness の policy_store／aggregate に1つ。）
   `tools/validate_fields.py`・`tools/write_draft.py` は これを呼ぶ**薄いラッパ**（二重実装しない）。表記の統一は
   soft な指針カードでなく決定的正規化（確定時に取りこぼしなく適用＝型/表記の保証）＝別の道具（線を混ぜない）。
   Memory 書き戻しは**保育士の明示承認＋型成立**でのみ発火（真の承認ゲート＝§9）。
2. **agents/（agentic・中身の決定）** — author（日誌）/ monthly_author（月案）/ child_record_author（保育経過記録）/
   nursery_record_author（保育要録）＝**単一 LlmAgent**（内部を多層化しない。巡回＝再作成は harness の
   `build_authoring_loop` が [作成→レビュー→ゲート] に包んで担う＝NEEDS_REVISION で author が指摘点を再作成）、
   reviewer＝Evaluator（日誌/月案/保育経過記録/保育要録で共用・開示前提の表現観点を含む）。巡回制御・早期終了は harness 側。
3. **improver/（二階・回す）** — 修正メモ→育つ指針カードの追加/改訂を自走提案。**既存カードとの意味的競合を
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

# 現状＝v0 実装済み（コード作業は一巡。残は各自 GCP のプロビジョニング/WIF と実様式・現場依存）

決定的部分（harness）は実装＋テスト済みで、LLM/GCP 非依存で稼働する。実装状況の詳細は
`docs/architecture.md`「実装状況（v0）と残課題」を正とする（ここでは要点のみ・二重管理しない）。

- **稼働範囲**: 保育日誌 ＋ **個別月案（L2 還流）** ＋ **クラス月案（園の実様式＝月間指導計画・L2 還流・§18）**
  ＋ **保育経過記録（期ごとの保育経過記録・L3 還流＝§19）**
  ＋ **保育要録（保育所児童保育要録・L4 還流＝それまでの保育経過記録すべての集積・小学校引継ぎ・年長のみ＝§19）**。
  日誌/月案/保育経過記録は**全年齢（0–2/3–5）**対応・要録は年長（5歳児＝5領域）専用（年齢分岐＝0–2:3つの視点＋
  生活記録必須／3–5:5領域・生活記録任意）。**保育日誌は手入力**（AI 生成を退役＝ヒアリング 2026-07：日誌は自分の言葉で打つ
  一次情報の蓄積口。web の docedit→`finalize_entry`→アーカイブ＝`author_kind=caregiver`＝L2/L3/L4 seed）。**校正AI**（`proofreader_agent`＝
  日本語チェック・言い換え提案）が入力後に叙述文へ**提案のみ**返す＝AI は著者でなく校正者（採否は保育士・事実は変えない・表記統一は notation が別途）。AI 生成書類の
  doc_type 分岐（`DocTypeRouter`＝root_agent）で振り分け（**既定＝クラス月案**・保育日誌はルータ外＝§18）。**クラス（組）＝一次
  エンティティ**（`record_store.Class`＋`children.class_id`・migration 0007・web 新タブ「クラス・園児」＝園の名簿管理・日誌 roster の素）。
  **クラス月案**は個別月案（1児単位）と別の doc_type＝**クラス全体（年齢帯）単位**の園の実様式（区分×領域グリッド
  ＋0–2 の個人目標小表）で、UI の「書類を作る」月案セグメントはクラス月案に一本化（個別月案はバックエンド・
  アーカイブ閲覧で温存）。0–2/3–5 とも様式は5領域グリッドで共通＝この書類では3つの視点分岐を適用しない（様式忠実・§18）。
  集積階層は **日誌→月案（L2）→保育経過記録（期・L3）→要録（年・L4）**（§19・全段実装済み）。**書類の依存モデル
  （2026-07-07 確定）**＝保育経過記録:該当期間の日誌＋**前回までの自己履歴すべて**／クラス月案:**クラス児童の保育経過記録
  すべて＋それまでのクラス月案すべて＋経過記録に未反映の日誌**（前月日誌ベースを置換・**児童別境界**＝`covered_until_by_child`＝記録が遅れている児も落とさない）／
  要録:それまでの保育経過記録すべて（全期・日誌は足さない）。「すべて」は年度跨ぎ可・seed はアーカイブから自動取得（未接続降格）。
- **実装済み（コード）**: レビュー APPROVED 早期終了（`ApprovalGate`/`is_approved`）/ 確定処理（`FinalizeAgent(kind)`＋
  `harness/finalize.py`・日誌/月案/保育経過記録）/ **月案パス＋L2 還流**（`monthly_author` が `fetch_reference(prev_month_diaries)` で取得）/
  **保育経過記録パス＋L3 還流**（期間日誌＋前回記録を `fetch_reference` で取得・開示前提の表現指針＝§19）/
  **保育要録パス＋L4 還流**（それまでの保育経過記録すべてを `fetch_reference(prev_child_records)` で取得・
  小学校引継ぎ＝開示前提・最終年度に至るまでの育ちは `recall_child_history` 参照＝§19）/
  HITL（`ask_caregiver`・`awaiting_caregiver_approval`）/ Memory Bank 配線＋**真の承認ゲート**（書き戻しは
  `caregiver_approved`＋型成立でのみ・`mark_caregiver_approved`・§9/§13）/
  **育つ指針＝構造化カード（§8 v1）**（`policy_store`＝決定的 CRUD/render/完全重複ガード/履歴＝「回した証拠」・
  **scope＝共通/保育日誌/月案/保育経過記録/保育要録**・improver は read→propose（意味的競合の申告）→ask（比較相談）→commit（保育士決定で即反映）の4ツール・eval は decouple）/
  **ひらがな表記DX＝表記正規化（`notation_store`）**（「子供→子ども」「友達→友だち」・混入スペース除去を確定時に決定的に適用＝
  取りこぼしゼロ・叙述系フィールド限定で仮名/タグ/日付は不変・保育士が編集辞書で追加/編集/削除・`notation_books`＋migration 0004・
  web `/api/notation`＋「表記ルール」タブ・降格safe）/
  **eval ゲート本採点**（`eval/test_config.json`＝3軸 rubric＋must_fix・judge 3票多数決・
  `gate_policy.json`＝軸/ケースfloor・全ケース×全rubric coverage必須・`run_gate.py --strict` は
  採点不能/欠落/baseline未確立も非0終了・**CI 品質回帰専用**）/
  **main 比 baseline 保存**（committed `eval/baseline.json`・`gate_policy.json` の非劣化マージン0.05以内で比較
  〔27セル中1セルのjudge揺れだけ許容・軸/ケースfloorは別途必須〕／`--update-baseline` は
  完全採点時だけ意図的に更新し通常PRでレビュー・nightly自動コミットは禁止）/
  **eval ケース 9 件**（保育経過記録6＋保育要録3・日誌16は手入力化で撤去済み・実在しない仮名ロスターのみ・現場に即した内容）/ ツールの降格（RAG/Memory 未設定でも落ちない）。
- **配信（層A）**: `Dockerfile`/`deploy.yml`/`eval-gate.yml`（WIF）・決定論 CI（`ci.yml`）。**本番運用ハードニング**
  （非root/PID1 SIGTERM グレースフル・max-instances 上限・専用実行SA・DATABASE_URL の Secret Manager 化・構造化 JSON ログ）を
  配線し docker build→起動→SIGTERM を実機確認済み（GCP 側の一度きり設定＝`docs/ライブ実行手順.md`「本番運用ハードニング」）。
- **標準様式への準拠＋制度用語是正**: `write_draft`/`write_monthly_draft` をネット調査で裏取りした 0–2 個別の標準様式へ
  （養護2本柱の分離・個別の生活記録＝食事/睡眠/排泄/機嫌体調・本日のねらい・月齢・養護→教育の順）。3つの視点/10の姿の
  文言誤り2件を告示準拠に是正。`LifeRecord` スキーマ＋年齢分岐は validate/draft/finalize/E2E/eval まで同調・テスト済み（§18・§10）。
- **保育士向け配布 UI（`web/`・B-full）**: `/app/` の保育士 SPA＝**上位4タブ**（**書類を作る**（日誌/月案/保育経過記録/保育要録を**カテゴリ別グループ表示の種別メニュー**
  で統合＝4カテゴリ〔指導計画/保育記録/保護者連携/園運営〕・**今後対応予定〔年間指導計画/週案/日案/連絡帳/おたより/勤務シフト〕は灰色の非選択 placeholder＝ロードマップ提示**・`DOC_CATEGORIES`/`renderDocMenu`。
  **保育日誌は手入力フォーム**＝`diaryform.js`＝クラス選択→在籍児 roster を空欄で並べ AI を通さない／月案/経過記録/要録は共通 ADK フロー＝`docflow.js`）／
  **育てる**（＝2サブタブ **指針を育てる**｜**表記ルール**。
  仕組みは分離のまま（policy_store＝agentic な勘所／notation_store＝決定的な統一・§5）で、保育士から見た「教える場所」を1タブに集約する
  presentation の統合。「指針を育てる」には**対象書類セレクタ**（すべて/共通/日誌/月案/保育経過記録/要録＝PolicyScope と 1:1）を置き、選ぶとカードデッキを
  「共通＋その書類」に絞り込み＝反映先を可視化し、`/api/improve` に `target_scope` を送って提案 scope の既定にする＝改善AIは既定として尊重しつつ
  内容的に共通と判断したら ask で提案）／**クラス・園児**（園の名簿管理＝`classes.js`・クラス定義＋園児登録/割当＝`/api/classes`・
  `record_store.Class`＋`children.class_id`・migration 0007＝日誌手入力フォームの roster・年齢帯自動決定の素）／**書類を見る**（アーカイブ閲覧＋**アップロード取込**＝
  `record_store` の確定書類をファイルシステム風ツリー〔種別→子ども→書類〕で辿り→クリックで整形テキスト＋帳票PDF を確認＝`records.js`・`GET /api/records`／`GET /api/records/{id}`
  ＝`record_store.get_document`・読取なので非ゲート・未接続は正直に降格・参照データの点検にも使える。**閲覧だけでなくアーカイブ済み書類を編集・（再）承認できる**〔右ペイン「編集する」→`docedit.js`→`/api/finalize-edit`→`/api/records`〔`author_kind="caregiver"`・新版〕・「承認する」→`/api/records/approve`。**承認済みを編集すると承認は失効し finalized へ戻る**＝record_store が demote〕。外から特定書類を編集モードで開く `records.openDoc(id,{edit,focus})` を公開〔クラス月案作成時の「評価未記入の日誌へ飛んで記入」導線が使う＝下記〕。**取込**＝各種別フォルダ〔＋personal 種別の子フォルダ〕の「取り込む」から
  既存ファイル〔PDF/Word/Excel〕を選び、`POST /api/parse-upload`〔`web/upload_extract`＝format 変換＋`web/upload_parse`＝`agents/upload_parser_agent` を1パス駆動→対象キー/child/age_band を保育士入力で権威的上書き→`finalize_entry`。LLM 口なので利用枠を予約〕で既存スキーマ entry に解析→**`docedit.js` で確認・修正**→`/api/finalize-edit`→`/api/records`〔`author_kind="imported"`〕保存＝以後 L2/L3/L4 seed として自動参照。生ファイルは保存しない〔PII blob を残さない〕））。日誌/月案/保育経過記録/保育要録は
  ADK ネイティブ REST をフロントが直接駆動（HITL は `function_response` 再送で再開。日誌は年齢帯チップ・保育経過記録は期間指定＋
  期間日誌＋前回までの記録 seed・保育要録は年度指定＋それまでの保育経過記録すべて seed＝`GET /api/records/child-record-entries`・クラス月案は seed 3系統＝`GET /api/records/class-monthly-seed`）。**確定下書きは標準様式の見た目の編集フォーム（`docedit.js`）で
  保育士が欄ごとに自由に編集**でき、保存時 `/api/finalize-edit`（harness `finalize_entry` 中継）で再検査・再整形→承認（`PATCH`
  で `caregiver_approved`）。タグ語彙は `/api/form-meta`（schemas Enum が SSOT）。**現場でそのまま綴じる最終形＝園の帳票PDF**は
  「帳票PDFをダウンロード」→ `/api/export-pdf`（`web/chohyo_pdf.py`＝ReportLab。日誌/月案＝A4 縦・欄順は標準様式に一致、保育経過記録＝**A4 横の年間マトリクス**（行=領域×列=4期・実様式準拠・過去期の列はアーカイブの保存済み保育経過記録から自動で埋める＝同じ子・同じ年度のみ・未接続は今回の期のみ）・
  **末尾に確認印欄（担任/主任/園長）**・**描画のみ／型の保証は harness**・日本語は IPAex ゴシック `web/fonts/ipaexg.ttf` を埋め込み＝閲覧側フォント非依存・純 pip で Dockerfile 不変・非ゲート）。
  **Word 編集版＝園の実 Word 様式に流し込んだ .docx** は「Word様式でダウンロード」→ `/api/export-docx`（`web/docx_fill.py`＝python-docx で
  `web/templates/*.docx` を埋める・純pip・docx→PDF のサーバ変換はしない・対応 kind＝保育経過記録/クラス月案（園フォーム全欄）/月案/保育要録を `/api/config` の `docx_kinds` で出し分け）。
  **改善エージェント（指針を育てる＝`policy.js`）は
  `/api/improve` の SSE 中継＋`/api/policy`（指針カード＋変更履歴の閲覧）**。**表記ルール（`notation.js`）は `/api/notation`
  の CRUD（保育士が表記辞書を追加/編集/削除・書込は辞書荒らし防止でゲート・LLM 非課金）**。
  **👍👎＋ひとことの軽量フィードバック導線（`feedback.js`・2026-07-08）**＝確定/承認画面・アーカイブ詳細に置き、送信で文書＋版に
  紐付け保存（`/api/records/feedback`＝harness `record_store.Feedback`・migration 0008）、ひとことがあれば「この気づきを指針に活かす」で
  **その場（インライン）に改善エージェントを展開**（`makePolicy` を再インスタンス化＝`/api/improve` の `feedback` を実値化・別エントリ維持・
  doc kind→scope は `scopes.js` に一本化）＝書類作成を通して「回す」が進む。improver は毎回カードを作らず「一般化できる勘所か」を判断
  （固有なら更新不要で終える）。eval とは decouple のまま・Memory Bank 書き戻しとは別物。Google Sign-In と LLM 利用枠で LLM を回す口を保護。
  実機検証済み（creds 有・gemini-2.5-pro＋Memory Bank）／非LLM面は `tests/test_web.py`。規約は `web/CLAUDE.md`。
- **接続済み**: Gemini/Vertex（ADC＋`GOOGLE_CLOUD_PROJECT`/`GEMINI_MODEL`）。既定モデル＝`gemini-3.5-flash`は
  Vertex の **global 専用**なので、生成モデルだけ `MODEL_LOCATION`（既定 global）に固定し、RAG/Memory は
  `GOOGLE_CLOUD_LOCATION`（regional・global 不可）のまま分離する（`models.build_model`＝§11）。eval の本採点は
  judge（rubric LLM）の genai client が env で Vertex を判定するため、`run_gate.py` の CLI が `.env` を
  自動 load する（未 load だと "No API key" で silently 採点不能になるのを防ぐ）。
- **Google Sign-In（Phase 3）**: `/` は案内画面、Google 公式ボタンの popup callback（同一Origin の
  `POST /auth/google`）は `web/auth.py` が ID token（署名/audience/期限/email_verified）＋案内画面が発行する
  署名付き専用 cookie のログイン CSRF token（double-submit・有効な cookie は使い回し＝favicon 等の自動リクエストや
  別タブの再描画で回転させない）を検証し、署名付き session を作る。`/app/`・API・ADK 口は未ログインで fail-closed、Cloud Run IAP は使わない。`users.google_subject`（migration 0010）が
  Google の不変 `sub` を正として auto-provision・email 変更を追随し、actor は検証済み session ＞ 自己申告。
- **書類アーカイブ（Phase 1・本番運用ブラッシュアップ 2026-07）**: `harness/record_store`＝Cloud SQL PostgreSQL
  （children/documents/document_versions/audit_events/**feedback**・Alembic＝repo root `migrations/`・`uv run alembic upgrade head`）。
  **書類フィードバック（`Feedback`＝👍👎＋ひとこと・migration 0008・`save_feedback`/`list_feedback`）は独立テーブル**＝確定/承認画面から
  送る評価を document＋その版に紐付けて残す（§8「回す」の一次入力＋§12 eval 質的拡充の原資・audit_events〔操作の証跡〕とは別・降格safe）。
  確定/編集/承認を web（`/api/records` 系＋担当者名＝actor 自己申告）から版管理つきで永続化し、**L2/L3 の seed は
  アーカイブから自動取得**（scripts/web とも・未接続はサンプル降格＝eval/CI は DB 非依存）。`DATABASE_URL` 未設定は降格。
  **児童マスタは名前の3要素を分離**（migration 0006）＝`display_name`（呼び名＋敬称＝child_id 同定キー・不変）／
  `given_name`＋`gender`（男→くん/女→ちゃん固定・`compose_display_name`）／`family_name`（姓＝氏名欄用の本名・**AI 非生成・DB のみ§14**）。
  「書類を作る」で未登録名を選ぶと本名＋性別で新規登録（`POST /api/children`→`upsert_child`・書込ゲート）＝敬称ゆれ・重複児を構造で防ぐ。
  要録/保育経過記録の帳票PDF 氏名欄は本名（`get_child` の official_name＝姓＋名）で描画・未登録は呼び名へ降格。
- **残課題（コードだけでは閉じられない＝外部依存）**: ① 各自 GCP のプロビジョニング＋env 設定（RAG corpus＝`RAG_CORPUS` /
  Memory Bank＝`AGENT_ENGINE_ID` / 書類アーカイブ＝Cloud SQL＋`DATABASE_URL`。スクリプト・手順は実機/テスト済み・未設定は降格）/ ② 層A 実デプロイ・eval ゲートCI の有効化
  （Terraformのeval専用SAをapply＋リポジトリ変数 `EVAL_SA`。未設定/IAM不足はstrictで赤。
  baselineはmain相当を手動完全採点し通常PRで確立）/ ③ 特定園の実様式による微調整（§18・標準様式準拠まではコード到達済み・
  残るは欄差のヒアリング確定）/ ④ 現場の修正差分による eval ケースの質的拡充（PII 非コミットを守る）。詳細は architecture.md。
- 新たにスタブを足すときは**場当たりで埋めない**（`docs/設計コンテキスト.md` の該当節＋既存レイヤに沿う）。
  決定的ロジックの実体は harness/eval に1つ・tools は薄いラッパ（§5）を崩さない。

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
