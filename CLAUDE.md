概要・北極星・技術スタック・ディレクトリ構成・セットアップは @README.md を参照（重複させない）。
レイヤとコードの対応は @docs/architecture.md を参照。

# このプロジェクトの正（SSOT）と設計判断

- **最終的な正は Obsidian vault `google-cloud-hackathon` の `設計/プロダクト方針.md`（製品方針）と
  `設計/エージェント設計.md`（アーキ）**。リポジトリ外にあり Claude からは読めない。
- **リポジトリ内の設計参照は `docs/設計コンテキスト.md`（開発ハンドオフの凝縮版）→ `docs/architecture.md`
  （コード対応）の順に見る**。なお不明なら推測で埋めずユーザーに確認。両者が食い違ったら vault が正。
- コード内の docstring は設計コンテキストの節番号（§4＝アーキ全体像 / §5＝責務境界 / §6＝作成AI /
  §7＝レビューAI / §8＝改善エージェント / §9＝メモリ / §10＝スキーマ / §12＝eval / §19＝ヒアリング反映
  2026-07：児童票＝L3 集積・全年齢化）を参照する。崩さない。
- **構造・規約を変えたら本 CLAUDE.md と `docs/architecture.md` を同じ変更内で更新する**（規約と実態の乖離・
  リンク切れを防ぐ。改名・移動・SSOT の置き場変更は特に）。

# 開発コマンド（推測しないこと）

- 依存: `uv sync`（uv 推奨。`pip install -e ".[dev]"` でも可）
- ローカル実行: `adk run src/hoiku_agent`（CLI 対話）/ `adk web src`（開発 UI。agents dir＝`src/`・`/dev-ui/`）。
  **保育士向け配布 UI は `uvicorn server:app` → `http://localhost:8000/app/`**（日誌/月案/回す を1枚で・`web/`＝層A
  presentation。生成は ADK ネイティブ REST を直接駆動し自前 Runner は組まない＝§9。配布リンクは `.env` の
  `DEMO_PASSCODE` で LLM を回す口のみゲート＝コスト/濫用対策。規約は `src/hoiku_agent/web/CLAUDE.md`）。
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
  `tests/test_eval_cases.py`。品質回帰の実採点は `pytest tests/test_eval.py`（層B・要 `--extra eval` ＝
  `google-adk[eval]` ＋ LLM 資格情報）。**evalset JSON（`eval/cases/*.evalset.json`）に `ruff format` を当てない**（Python 扱いで壊れる）。
- lint: `ruff check .` / `ruff format .`（line-length=100, target=py311。`.` 指定は .py のみ整形）
- 認証/設定: `cp .env.example .env` → 記入 → `gcloud auth application-default login`
- 書類アーカイブ（任意・Phase 1）: `.env` に `DATABASE_URL`（Cloud SQL / ローカル Postgres）→
  `uv run alembic upgrade head`（スキーマ適用＝`migrations/`）。未設定は降格＝永続化なし・seed はサンプル
  （手順・Cloud SQL 作成は `docs/ライブ実行手順.md`）。
- 月案（doc_type=月案・L2 還流）は前月日誌を seed して回す専用入口 `uv run python scripts/run_monthly.py
  --child-id はるとくん --month 2026-07`（要 LLM 資格情報）。日誌は `adk web src`（doc_type 既定＝保育日誌）。
- 児童票（doc_type=児童票・L3 還流＝期間日誌の集積）は専用入口 `uv run python scripts/run_child_record.py
  --child-id はるとくん --period 2026-04〜2026-06`（要 LLM 資格情報。期間日誌を seed）。
- 配信（層A）: `Dockerfile`＝`uvicorn server:app`（Cloud Run・scale-to-zero・**非root/PID1 exec 形式で SIGTERM
  グレースフル**）。デプロイ＝`.github/workflows/deploy.yml`（WIF・**MUST ハードニング配線**＝`--max-instances`（`MAX_INSTANCES`
  var・既定4）/`--service-account`（`RUNTIME_SA` var＝最小権限・未設定は既定 SA 降格＋警告）/`DATABASE_URL` は
  Secret Manager 優先（`DATABASE_URL_SECRET` var・無ければ GH secret 平文降格）。GCP 側の一度きり設定は
  `docs/ライブ実行手順.md`「本番運用ハードニング」）/ eval ゲートCI＝`.github/workflows/eval-gate.yml`（nightly/手動・要 WIF+creds）。
- 可観測性: `src/hoiku_agent/logging_config.py`＝Cloud Run 向け構造化 JSON ログ（stdout 1行 JSON・severity・
  `X-Cloud-Trace-Context` 相関）。`server.py` 入口で `configure_logging()`＋`install_trace_middleware()`。
  Cloud Logging クライアントは手組みしない（マネージド昇格に委ねる）。ローカルは `K_SERVICE` 無しでテキスト降格（`LOG_FORMAT`/`LOG_LEVEL`）。
- 二階（改善エージェント）は **root_agent とは別エントリ・手動起動**（v0）。専用スクリプト
  `uv run python scripts/run_improver.py --diff "…" [--feedback "…"]` で起こす（要 LLM 資格情報）。
  document_pipeline には組み込まない。
- **ADK 探索の事実**: agents dir＝`src/`、agent package＝`hoiku_agent/`、`root_agent` は `agent.py` のみで
  トップレベル化、`__init__.py` の `from . import agent` を壊さない。`adk web` は `src/` を指して起動する
  （リポジトリ root で叩くと dropdown に出ない）。

# アーキ＝3責務（実装で混ぜてはいけない線。詳細は各層の CLAUDE.md）

1. **harness/（決定的・型の保証）** — 必須欄・年齢分岐・順序・集積・**doc_type分岐（router）**・指針カードストア・
   **表記正規化（ひらがな表記DX＝`notation_store`）**。LLM を呼ばない。**決定ロジックの実体はここに1つだけ**。
   `tools/validate_fields.py`・`tools/write_draft.py` は これを呼ぶ**薄いラッパ**（二重実装しない）。表記の統一は
   soft な指針カードでなく決定的正規化（確定時に取りこぼしなく適用＝型/表記の保証）＝別の道具（線を混ぜない）。
   Memory 書き戻しは**保育士の明示承認＋型成立**でのみ発火（真の承認ゲート＝§9）。
2. **agents/（agentic・中身の決定）** — author（日誌）/ monthly_author（月案）/ child_record_author（児童票）＝
   **単一 LlmAgent**（内部を多層化しない。巡回＝再作成は harness の `build_authoring_loop` が [作成→レビュー→ゲート]
   に包んで担う＝NEEDS_REVISION で author が指摘点を再作成）、reviewer＝Evaluator（日誌/月案/児童票で共用・
   開示前提の表現観点を含む）。巡回制御・早期終了は harness 側。
3. **improver/（二階・回す）** — 修正メモ→育つ指針カードの追加/改訂を自走提案。**既存カードとの意味的競合を
   精査し、競合は保育士に比較相談、保育士の決定で即反映**（add/supersede。番人＝意味的競合精査＋保育士決定）。
   指針編集の決定的実体は harness/policy_store（「回した証拠」＝カード内蔵の変更履歴）。**eval は取り込みから外す**
   （CI の品質回帰として温存＝decouple）。

**メモリ3分類**: 子ども長期記憶＝Agent Engine Memory Bank（repo外）／ 育つ指針＝構造化カード
（runtime の正は `DATABASE_URL` 設定時 **Cloud SQL の policy_books 1行（book 丸ごと JSONB・version 楽観ロック）**
＝書類アーカイブと同じ DB へ統合（Phase 2・GCS は廃止）。未設定はローカル `knowledge/文書作成指針.json`＝
git はシード（DB 行不在時のフォールバックシードも兼ねる）。agent は読み取り＝`read_policy`、
improver が保育士決定で即反映）／静的知識＝Vertex RAG（`knowledge/保育所保育指針/` は gitignore のRAGソース）。
「全部ファイルベース」にしない。なお **表記ルール辞書（ひらがな表記DX＝`notation_store`・`notation_books` 1行・
migration 0004・未設定はローカル `knowledge/表記ルール.json` シード）** は "メモリ" ではなく決定的な表記統一の
辞書（保育士が編集・harness が確定時に適用）＝育つ指針カードとは役割が別（agentic な勘所 vs 決定的な表記）。

# コード規約（このリポジトリ固有）

- 各モジュール冒頭に `from __future__ import annotations` を置く。
- ADK エージェントは **`build_xxx()` ファクトリ関数**で構築して返す（`build_author_agent` /
  `build_monthly_author_agent` / `build_child_record_author_agent` / `build_review_agent` / `build_improver_agent` /
  `build_document_pipeline` / `build_monthly_pipeline` / `build_child_record_pipeline` / `build_root_agent`）。
  トップレベルでインスタンス化しない（例外は `agent.py` の `root_agent` のみ）。
- エージェント間の受け渡しは **`output_key` → `state[...]`**（`state["draft"]` / `state["review"]`）。
  独自グローバルで渡さない。
- スキーマは `schemas/` の pydantic モデルに集約。同じ関心事を別所で二重定義しない。
- instruction（プロンプト）は各層の `prompts.py` に分離する。
- docstring・コメント・LLM プロンプトは日本語。

# 現状＝v0 実装済み（コード作業は一巡。残は各自 GCP のプロビジョニング/WIF と実様式・現場依存）

決定的部分（harness）は実装＋テスト済みで、LLM/GCP 非依存で稼働する。実装状況の詳細は
`docs/architecture.md`「実装状況（v0）と残課題」を正とする（ここでは要点のみ・二重管理しない）。

- **稼働範囲**: 保育日誌 ＋ **個別月案（L2 還流）** ＋ **児童票（期ごとの保育経過記録・L3 還流＝§19）**。
  いずれも**全年齢（0–2/3–5）**対応（年齢分岐＝0–2:3つの視点＋生活記録必須／3–5:5領域・生活記録任意）。
  doc_type 分岐（`DocTypeRouter`＝root_agent）で振り分け（既定＝保育日誌＝§3）。
- **実装済み（コード）**: レビュー APPROVED 早期終了（`ApprovalGate`/`is_approved`）/ 確定処理（`FinalizeAgent(kind)`＋
  `harness/finalize.py`・日誌/月案/児童票）/ **月案パス＋L2 還流**（`DigestPrepAgent`→`prev_month_digest`→`monthly_author`）/
  **児童票パス＋L3 還流**（`DigestPrepAgent`（period_prep）→`period_digest`→`child_record_author`・開示前提の表現指針＝§19）/
  HITL（`ask_caregiver`・`awaiting_caregiver_approval`）/ Memory Bank 配線＋**真の承認ゲート**（書き戻しは
  `caregiver_approved`＋型成立でのみ・`mark_caregiver_approved`・§9/§13）/
  **育つ指針＝構造化カード（§8 v1）**（`policy_store`＝決定的 CRUD/render/完全重複ガード/履歴＝「回した証拠」・
  **scope＝共通/保育日誌/月案/児童票**・improver は read→propose（意味的競合の申告）→ask（比較相談）→commit（保育士決定で即反映）の4ツール・eval は decouple）/
  **ひらがな表記DX＝表記正規化（`notation_store`）**（「子供→子ども」「友達→友だち」・混入スペース除去を確定時に決定的に適用＝
  取りこぼしゼロ・叙述系フィールド限定で仮名/タグ/日付は不変・保育士が編集辞書で追加/編集/削除・`notation_books`＋migration 0004・
  web `/api/notation`＋「表記ルール」タブ・降格safe）/
  **eval ゲート本採点**（`eval/test_config.json`＝3軸 rubric＋must_fix・`run_gate.py` が passed True/False・採点不能は None 降格・**CI 品質回帰専用**）/
  **main 比 baseline 保存**（committed `eval/baseline.json`・`run_gate` 既定で読み非劣化比較／`--update-baseline` で更新・nightly がコミットバック）/
  **eval ケース 22 件**（日誌16＋児童票6・実在しない仮名ロスターのみ・現場に即した内容）/ ツールの降格（RAG/Memory 未設定でも落ちない）。
- **配信（層A）**: `Dockerfile`/`deploy.yml`/`eval-gate.yml`（WIF）・決定論 CI（`ci.yml`）。**本番運用ハードニング**
  （非root/PID1 SIGTERM グレースフル・max-instances 上限・専用実行SA・DATABASE_URL の Secret Manager 化・構造化 JSON ログ）を
  配線し docker build→起動→SIGTERM を実機確認済み（GCP 側の一度きり設定＝`docs/ライブ実行手順.md`「本番運用ハードニング」）。
- **標準様式への準拠＋制度用語是正**: `write_draft`/`write_monthly_draft` をネット調査で裏取りした 0–2 個別の標準様式へ
  （養護2本柱の分離・個別の生活記録＝食事/睡眠/排泄/機嫌体調・本日のねらい・月齢・養護→教育の順）。3つの視点/10の姿の
  文言誤り2件を告示準拠に是正。`LifeRecord` スキーマ＋年齢分岐は validate/draft/finalize/E2E/eval まで同調・テスト済み（§18・§10）。
- **保育士向け配布 UI（`web/`・B-full）**: `/app/` の保育士 SPA＝**4タブ**（**書類を作る**（日誌/月案/児童票を種別セグメントで統合＝
  フロー本体は共通・入力欄と seed だけ切替。DocTypeRouter の doc_type 分岐と 1:1）／**指針を育てる**／**表記ルール**／**書類を見る**（アーカイブ閲覧＝
  `record_store` の確定書類を種別で絞り込み一覧→クリックで整形テキスト＋帳票PDF を確認＝`records.js`・`GET /api/records`／`GET /api/records/{id}`
  ＝`record_store.get_document`・読取なので非ゲート・未接続は正直に降格・参照データの点検にも使える））。日誌/月案/児童票は
  ADK ネイティブ REST をフロントが直接駆動（HITL は `function_response` 再送で再開。日誌は年齢帯チップ・児童票は期間指定＋
  期間日誌 seed）。**確定下書きは標準様式の見た目の編集フォーム（`docedit.js`）で
  保育士が欄ごとに自由に編集**でき、保存時 `/api/finalize-edit`（harness `finalize_entry` 中継）で再検査・再整形→承認（`PATCH`
  で `caregiver_approved`）。タグ語彙は `/api/form-meta`（schemas Enum が SSOT）。**現場でそのまま綴じる最終形＝園の帳票PDF**は
  「帳票PDFをダウンロード」→ `/api/export-pdf`（`web/chohyo_pdf.py`＝ReportLab。日誌/月案＝A4 縦・欄順は標準様式に一致、児童票＝**A4 横の年間マトリクス**（行=領域×列=4期・実様式準拠・過去期の列はアーカイブの保存済み児童票から自動で埋める＝同じ子・同じ年度のみ・未接続は今回の期のみ）・
  **末尾に確認印欄（担任/主任/園長）**・**描画のみ／型の保証は harness**・日本語は IPAex ゴシック `web/fonts/ipaexg.ttf` を埋め込み＝閲覧側フォント非依存・純 pip で Dockerfile 不変・非ゲート）。
  **改善エージェント（指針を育てる＝`policy.js`）は
  `/api/improve` の SSE 中継＋`/api/policy`（指針カード＋変更履歴の閲覧）**。**表記ルール（`notation.js`）は `/api/notation`
  の CRUD（保育士が表記辞書を追加/編集/削除・書込は辞書荒らし防止でゲート・LLM 非課金）**。`DEMO_PASSCODE` で LLM を回す口のみゲート。
  実機検証済み（creds 有・gemini-2.5-pro＋Memory Bank）／非LLM面は `tests/test_web.py`。規約は `web/CLAUDE.md`。
- **接続済み**: Gemini/Vertex（ADC＋`GOOGLE_CLOUD_PROJECT`/`GEMINI_MODEL`）。既定モデル＝`gemini-3.5-flash`は
  Vertex の **global 専用**なので、生成モデルだけ `MODEL_LOCATION`（既定 global）に固定し、RAG/Memory は
  `GOOGLE_CLOUD_LOCATION`（regional・global 不可）のまま分離する（`models.build_model`＝§11）。eval の本採点は
  judge（rubric LLM）の genai client が env で Vertex を判定するため、`run_gate.py` の CLI が `.env` を
  自動 load する（未 load だと "No API key" で silently 採点不能になるのを防ぐ）。
- **IAP 認証の土台（Phase 3 着手）**: `web/iap.py`（`IAP_AUDIENCE` 設定時のみ IAP JWT を署名検証・未設定は
  完全降格＝ヘッダを信用しない）＋ `record_store.users`/`touch_user`（検証済み email の auto-provision・
  migration 0002）＋ actor 解決（検証済み email ＞ 自己申告）。**IAP 自体の有効化は運用判断＝未実施**
  （現行の公開デモ＋パスコード運用は不変）。
- **書類アーカイブ（Phase 1・本番運用ブラッシュアップ 2026-07）**: `harness/record_store`＝Cloud SQL PostgreSQL
  （children/documents/document_versions/audit_events・Alembic＝repo root `migrations/`・`uv run alembic upgrade head`）。
  確定/編集/承認を web（`/api/records` 系＋担当者名＝actor 自己申告）から版管理つきで永続化し、**L2/L3 の seed は
  アーカイブから自動取得**（scripts/web とも・未接続はサンプル降格＝eval/CI は DB 非依存）。`DATABASE_URL` 未設定は降格。
- **残課題（コードだけでは閉じられない＝外部依存）**: ① 各自 GCP のプロビジョニング＋env 設定（RAG corpus＝`RAG_CORPUS` /
  Memory Bank＝`AGENT_ENGINE_ID` / 書類アーカイブ＝Cloud SQL＋`DATABASE_URL`。スクリプト・手順は実機/テスト済み・未設定は降格）/ ② 層A 実デプロイ・eval ゲートCI の有効化
  （GCP の WIF 設定＋リポジトリ変数。未設定なら job は skip。**baseline 保存・比較はコード実装済み**＝committed
  `eval/baseline.json`・WIF 有効化で nightly が初回採点して埋める）/ ③ 特定園の実様式による微調整（§18・標準様式準拠まではコード到達済み・
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
