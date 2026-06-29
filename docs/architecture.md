# アーキテクチャ（設計のコード対応）

最終的な正は Obsidian vault の `設計/プロダクト方針.md` / `設計/エージェント設計.md`（repo 外）。
リポジトリ内の設計参照は `docs/設計コンテキスト.md`（開発ハンドオフ）。本ファイルはそれをコード構造に
対応づけた索引。構造を変えたら本ファイルと `CLAUDE.md` を同じ変更内で更新する。

## 3責務 ↔ コード（設計コンテキスト §5 責務境界）

| 責務 | コード | 役割 | 性質 |
|---|---|---|---|
| ① 型の保証（§5） | `harness/` | 必須欄・年齢分岐・順序・集積・doc_type分岐・git適用。決定ロジックの唯一実装 | 決定的 |
| ② 中身の決定・作成AI（§6） | `agents/author_agent.py`（日誌）/ `agents/monthly_author_agent.py`（月案）＝単一 `LlmAgent`＋tools | 情報収集（Agentic RAG）・質問生成・「姿→ねらい/評価」変換・前月集積の要約 | Agentic |
| ② レビューAI（§7） | `agents/review_agent.py`（`LlmAgent`・日誌/月案で共用） | 別視点で点検・APPROVED まで巡回（制御は harness） | Agentic |
| ③ 改善エージェント（§8） | `improver/`（別エントリ・手動起動） | 修正メモ→指針カードの追加/改訂を自走提案・**意味的競合を精査**し保育士の決定で**即反映**（番人＝意味的競合精査＋保育士決定） | Agentic |
| 品質回帰の番人（§12） | `eval/`（cases/・judges/・`test_config.json`・`run_gate.py`） | 3軸 rubric で採点→main 比 非劣化＆must_fix 0。**CI の品質回帰テスト専用（prompt/モデル/指針の変更を守る）。improver の取り込みには関与しない＝decouple** | 決定的（CI） |
| 配信UI（層A・§11） | `web/`（`routes.py`・`improver_stream.py`・`static/`） | 保育士向け配布 UI（`/app/`）。**4つ目の責務ではない presentation**：日誌/月案は ADK ネイティブ REST を直接駆動（自前 Runner なし）、improver（指針を育てる）だけ SSE 中継 | 中継・描画 |

## harness 内訳（§5 物理マッピング）

| ファイル | 関数 | 役割 |
|---|---|---|
| `harness/router.py` | `DocTypeRouter` / `build_root_agent` | `state["doc_type"]` で日誌/月案パイプラインを振り分ける決定的分岐（root_agent の実体・既定＝保育日誌＝§3） |
| `harness/pipeline.py` | `build_document_pipeline` / `build_authoring_loop` / `ApprovalGate` / `FinalizeAgent`(kind) / `is_approved` / `persist_visit_to_memory`(+`_should_persist_visit`) / `mark_caregiver_approved`(+`CAREGIVER_APPROVAL_KEY`) | 日誌：authoring_loop（[author→reviewer→ApprovalGate] を巡回・NEEDS_REVISION で author が再作成・APPROVED 早期終了）→ finalize の順序制御。`after_agent_callback`＝**保育士の明示承認＋型成立**のときのみ来園を Memory Bank へ書き戻す（真の承認ゲート＝§9/§13） |
| `harness/monthly.py` | `MonthlyPrepAgent` / `build_monthly_pipeline` | 月案：前月日誌を child_id 別に決定的集計（L2 還流）→ 月案 author の authoring_loop（日誌と共用・再作成）→ finalize(kind="monthly")（§3/§4/§10） |
| `harness/schema_check.py` | `validate_fields` / `validate_monthly_fields`(+`_required_tag_type`) | 必須欄＋年齢分岐（0–2＝3つの視点 / 3–5＝5領域）。日誌/月案で分岐の実体を共用 |
| `harness/draft.py` | `write_draft` / `write_monthly_draft` | pydantic（DiaryEntry/MonthlyPlan）→ 様式整形（10の姿/3つの視点/5領域タグ明示） |
| `harness/finalize.py` | `finalize_document` / `finalize_monthly_document` / `parse_draft_to_entry` / `parse_draft_to_plan` | author 出力（JSON）の復元 → 確定 validate/write（pipeline 末尾で実行する純ロジック・`_finalize` で共用）。日誌の **date（記録日）は harness が所有する決定的メタデータ**＝`doc_date` で復元前に注入し author 出力を上書き（LLM に日付を生成させない＝雛形 echo 耐性。clock を持たず純関数を保つため現在日付の解決は `pipeline.FinalizeAgent`） |
| `harness/aggregate.py` | `aggregate_by_child` / `prev_month_digest` / `format_digest_for_prompt` | 月⇔日の集積（child_id 別）と L2 還流の state 用 digest・人間可読テキスト。要約生成は月案 author |
| `harness/policy_store.py` | `load_book`/`save_book` / `add_card`/`supersede_card`/`remove_card` / `render_to_text` / `find_exact_duplicate` / `card_view`/`history_view`/`book_view` / `store_status` | 育つ指針＝構造化カードストア（`knowledge/文書作成指針.json`）の決定的 CRUD・完全重複ガード（安全網）・履歴・テキスト再生・API view。**指針編集の決定的実体はここに1つ**（improver/read_policy は薄いラッパ）。clock は外部注入 |
| `harness/git_ops.py` | `commit_policy_book` | 即反映済みカード JSON の git 証拠 commit（プロダクトの git 操作。既定 dry_run・降格付き） |

## ツール（§6・4–8個のプリミティブ）

`tools/`（agent が呼ぶプリミティブ）: `recall_child_history`(子の前回までの像＝Memory Bank・`tool_context.search_memory`・未接続で降格) /
`search_guideline`(Vertex RAG・未設定で降格) / `read_policy`(育つ指針 HEAD) / `ask_caregiver`(HITL＝`LongRunningFunctionTool`) /
`validate_fields`(生成途中の自己点検)。配線は author（日誌）＝上記全部 / monthly_author（月案）＝`recall_child_history`・
`search_guideline`・`read_policy`・`ask_caregiver`（月案の確定 validation は harness の `validate_monthly_fields` が末尾実行・自己点検ツールは未配線）/
reviewer＝`read_policy`・`search_guideline`・`recall_child_history` のみ。
`validate_fields`・`write_draft` の決定的実体は harness（§5）で、最終の確定 validation・整形出力は harness が末尾で実行する＝
`write_draft` は agent tool ではない。`search_past_documents`(過去書類アーカイブ＝ローカル架空児記録ストア)は v0 では **agent に未配線**
（継続把握は `recall_child_history` に一本化＝§9。過去書類の引用が実需になれば復活。月⇄日集積は決定的に `aggregate_by_child`）。
improver 固有: `improver/tools.py`（`read_policy_cards`／`propose_policy_card`＋意味的競合の申告＋完全重複ガード／
`commit_policy_card`＝保育士決定で即反映・`policy_store` と `git_ops.commit_policy_book` を呼ぶ薄いラッパ）。
**run_eval/open_pr は撤去**（eval は CI 専用に decouple）。GCP 系（RAG/Memory）は config 未設定時に安全に降格する。

## メモリ3分類（§9）

| 対象 | 置き場 | 参照 |
|---|---|---|
| 子ども別 長期メモリ | Agent Engine Memory Bank（repo外） | 読み＝`recall_child_history`／書き戻し＝`persist_visit_to_memory`（pipeline の `after_agent_callback`・**保育士の明示承認＝`caregiver_approved` ＋型成立**でのみ発火＝真の承認ゲート）。配線は `--memory_service_uri=agentengine://<id>`（`config.memory_service_uri`／`server.py`）。未設定で降格 |
| 育つ文書作成指針 | git `knowledge/文書作成指針.json`（構造化カード） | agent は読み取り（`read_policy`＝`render_to_text`）／improver が**保育士の決定で即反映**（add/supersede・`policy_store`） |
| 静的ナレッジ（指針解説・10の姿） | Vertex RAG（`knowledge/保育所保育指針/` は gitignore のソース） | `search_guideline` |

## データフロー

```
観察メモ（音声/手入力）＋ state["doc_type"]（既定＝保育日誌）
  └─ harness: DocTypeRouter (root_agent) … doc_type で日誌/月案パイプラインを決定的に振り分け（§10）
       │
       ├─[日誌]─ document_pipeline (SequentialAgent)
       │    ├─ authoring_loop (LoopAgent: author→reviewer→approval_gate を最大3巡)
       │    │    ├─ author (LlmAgent)  … 不足は ask_caregiver(HITL) / RAG・記録・子メモリを収集 / 指針準拠で
       │    │    │                        下書き＋DiaryEntry JSON → state["draft"]
       │    │    ├─ reviewer (LlmAgent) … 別視点で点検 → state["review"]
       │    │    └─ approval_gate … APPROVED で早期終了 / NEEDS_REVISION なら次巡で author が指摘点を再作成
       │    └─ finalize(kind=diary) … 記録日を解決（state["doc_date"]｜本日）→ 復元時に date 注入 →
       │                              validate_fields/write_draft → state["final_document"]/["validation"]、
       │                              awaiting_caregiver_approval=True（HITL）
       │
       └─[月案]─ monthly_plan_pipeline (SequentialAgent)
            ├─ monthly_prep (BaseAgent) … 前月日誌（state["prev_month_entries"]）を child_id 別に集計（L2 還流）
            │                              → state["prev_month_digest"]＋集計テキストを提示
            ├─ authoring_loop （日誌と共用: monthly_author→reviewer→approval_gate を巡回・再作成）
            │    └─ monthly_author (LlmAgent) … 前月集積＋子メモリから「前月の姿/評価反省」を要約・ねらい化 → state["draft"]
            └─ finalize(kind=monthly) … 復元→validate_monthly_fields/write_monthly_draft → state["final_document"]
       │
       └─[after_agent_callback] persist_visit_to_memory … **保育士の明示承認（caregiver_approved）＋型成立**の
                                  ときのみ来園を子の Memory Bank へ書き戻す（真の承認ゲート＝§9/§13。未配線/未承認は降格・保留）
出力（確定書類）＋ 保育士の修正メモ → 改善エージェント（別エントリ）が指針カードを提案 → 意味的競合は
                                  保育士に比較相談 → 保育士の決定で即反映（policy_store・「回した証拠」＝カード履歴）
  ［別系統］eval（層B・run_gate＝3軸 rubric）＝CI の品質回帰テスト（prompt/モデル/指針の変更を守る・improver とは decouple）
```

## 実装状況（v0）と残課題

v0 で稼働する範囲は **保育日誌（0–2 個別）＋ 個別月案（0–2・L2 還流）**（§3「日誌先行 → 月案は集積に乗せる」）。
実装済み（決定的部分はテスト済み・GCP/LLM 非依存で稼働）:
- **doc_type 分岐 ＋ 月案パス ＋ L2 還流**：`DocTypeRouter`（root_agent）が doc_type で日誌/月案を振り分け、
  月案は `MonthlyPrepAgent` が前月日誌を child_id 別に決定的集計（`prev_month_digest`）→ `monthly_author` が
  要約・ねらい化 → `validate_monthly_fields`/`write_monthly_draft` で確定（§3/§4/§10）。`MonthlyPlan` スキーマ・
  月案決定論E2E（ルータ分岐/L2 還流/確定）まで実装・テスト済み。デモ入口＝`scripts/run_monthly.py`。
- レビュー巡回（`build_authoring_loop`＝[作成→レビュー→ApprovalGate]）：NEEDS_REVISION で作成AIが指摘点を
  再作成し、APPROVED 早期終了（`ApprovalGate`／`is_approved`。判定は1行目の verdict＝prompts.py）。再質問しない
  revision mode・date 等の機械的メタを指摘させない注意書きは prompts.py。
- HITL 関門：`ask_caregiver`＝`LongRunningFunctionTool`、確定段の `awaiting_caregiver_approval` フラグ。
- 出力の最終 validation／整形（`FinalizeAgent(kind)`＋`harness/finalize.py`。日誌/月案で `_finalize` を共用）。
- **育つ指針＝構造化カード（§8 v1）**：`policy_store`（決定的 CRUD/render/完全重複ガード/履歴）＋`git_ops.commit_policy_book`（証拠 commit・既定 dry_run）。`improver` は4ツール（`read_policy_cards`→`propose_policy_card`＝意味的競合の申告→`ask_caregiver`＝比較相談→`commit_policy_card`＝保育士決定で即反映）。eval は取り込みから decouple（CI 専用）。
- **決定論E2E（結合テスト）**：`tests/test_e2e/`。`FakeLlm` 注入で日誌/月案パイプラインを実 ADK ランタイムに
  end-to-end で通し、連結・APPROVED 早期終了・**NEEDS_REVISION での再作成（2枚目が確定）**・巡回上限・確定3経路・
  HITL 不発火・**真の承認ゲートの書き戻し**・**L2 還流/ルータ分岐**を creds 不要・決定的に検証（品質採点は層B eval＝別系統）。起動は `/e2e` skill。
- **Memory Bank 配線（読み＋書き戻し）＋ 真の承認ゲート**：`config.memory_service_uri`（`agentengine://<id>`）→
  入口 `server.py`（ADK の `--memory_service_uri` 自動配線）。読み＝`recall_child_history`、書き戻し＝
  `persist_visit_to_memory`（`after_agent_callback`）。書き戻しは **保育士の明示承認（`caregiver_approved=True`＝
  `mark_caregiver_approved`）＋型成立**でのみ発火（型成立を承認の代理にしない＝§9/§13）。発火/保留/降格を決定論E2E で検証。
- **eval ゲートの本採点（3軸 rubric 配線）**：`eval/test_config.json` が ADK ネイティブの
  `rubric_based_final_response_quality_v1` に3軸（`axis_*`）＋must_fix（`mustfix_*`）を rubric として載せる。
  `eval/run_gate.py` が rubric 採点 → `aggregate_rubric_scores`（軸平均＝ケーススコア／mustfix の no＝違反）→
  `decide_gate`（main 比 非劣化 かつ must_fix 0）で **passed=True/False** を返す（採点不能時のみ None 降格＝偽の緑なし）。
  判定式の純関数は `tests/test_eval_gate.py` で LLM 非依存に検証。rubric 6件が config から評価器へロードされること、
  採点経路が全段（推論→評価→抽出）を例外なく走り creds 無で None 降格することを実機確認済み。**さらに creds 有で
  16 ケースを live 採点し本採点が end-to-end に通ることを確認**（その過程で custom BaseAgent＝ApprovalGate/
  FinalizeAgent/MonthlyPrepAgent がイベントに `invocation_id` を伝播していなかった不具合を是正＝ADK eval の
  「invocation 数＝conversation 数」整合に必須。回帰防止は `tests/test_e2e/test_pipeline_e2e.py`）。
  既知の限界：rubric は judge の echo テキストで照合されるため（ADK 仕様）、長い rubric 文面（axis_guideline_alignment）は
  judge が一部を言い換えると照合漏れし、その軸が一部ケースで欠落する（軸平均は present のみで計算・mustfix は不影響）。
  rubric 文面の echo 安定化は今後の調整（残課題）。
- **main 比 baseline の保存（committed）**：`eval/baseline.json` に main の eval 平均を保存し、`run_gate` が
  既定で `load_baseline` して PR の非劣化比較に使う（`build_baseline_record`/`write_baseline`／不在・壊れは
  `baseline_mean=None`＝比較なしへ降格＝偽の赤なし）。更新は `run_gate.py --update-baseline`（採点不能なら
  据え置き）で、nightly/手動の main eval-gate がこれを実行しコミットバックする（`eval-gate.yml`・`contents: write`）。
  **live 採点で実値シード済み（main mean≈0.95・must_fix 0）**。load/write/降格・file 優先順位は
  `tests/test_eval_gate.py` で LLM 非依存に検証。
- **eval ケース**：`eval/cases/diary_0_2.evalset.json` を 16 件（架空児のみ・現場の多様な状況）に拡充。
  件数≥15・参照ドラフトが型を通る・実名なしを `tests/test_eval_cases.py` で決定論検査。
- **配信（層A）**：`Dockerfile`＋`.dockerignore`（`uvicorn server:app`・scale-to-zero。指針ファイル＋`eval/baseline.json` のみ同梱）、
  `.github/workflows/deploy.yml`（WIF で `gcloud run deploy --source .`）、`.github/workflows/eval-gate.yml`
  （nightly/手動・WIF で creds 採点）。決定論 CI（`ci.yml`）は従来どおり毎PR・creds 不要。
  docker build → コンテナ起動で `/docs` 200 を実機確認済み。
- **保育士向け配布 UI（`web/`・B-full）**：`server.py` が `register_web_ui(app)` で `get_fast_api_app` に同居させる。
  保育士 SPA＝`/app/`（`/` も着地）、dev UI＝`/dev-ui/`、自前 API＝`/api/*`。日誌/月案はフロントが ADK ネイティブ REST
  （`/run_sse`・session 作成で月案 seed・`PATCH` 承認・`function_response` で HITL 再開）を直接駆動（自前 Runner なし＝§9）。
  改善エージェント（指針を育てる）は `improver_stream.py` が `build_improver_agent` を InMemoryRunner で
  SSE 駆動（別エントリ維持）し、`policy.js`（温かい1タブ）が「指針カード閲覧＋変更履歴／提案→意味的競合の
  比較相談→保育士決定で即反映」をライブに描く。`/api/policy`＝カード＋履歴＋store。LLM を回す口（`/api/improve`）
  だけ `DEMO_PASSCODE` でゲート（配布リンクのコスト/濫用対策）。
  非LLM面（配線・静的配信・コストゲート・`/api/policy` 形・`/` 着地）は `tests/test_web.py` で決定論検証。`web/CLAUDE.md` に規約。

残課題（**外部リソース・実データ・各自 GCP 設定に依存。コードは降格付きで配線済み**＝コードだけでは閉じられない）:
- **各自 GCP のプロビジョニング＋ env 設定**（コード・スクリプトは実機検証済み）:
  - Vertex RAG corpus：`uv run python scripts/provision_rag_corpus.py --create`（新規 GCP は RagManagedDb を
    serverless へ REST 切替＋Vector Search API・埋め込みは `text-multilingual-embedding-002`）→ `.env` の `RAG_CORPUS`。
    未設定は `search_guideline` 降格。
  - Memory Bank：`uv run python scripts/provision_memory_bank.py --create`（生成モデル＋日本語/子の姿カスタマイズ）
    → `.env` の `AGENT_ENGINE_ID`。未設定は InMemory 降格。
  - 手順は `docs/ライブ実行手順.md`。Gemini/Vertex 自体は接続済み（ADC＋`GOOGLE_CLOUD_PROJECT`/`GEMINI_MODEL`）。
    既定モデル `gemini-3.5-flash` は Vertex **global 専用**のため、生成だけ `MODEL_LOCATION`（既定 global）へ固定し、
    RAG/Memory は `GOOGLE_CLOUD_LOCATION`（regional）のまま分離する（`src/hoiku_agent/models.py`＝`build_model`）。
- **層A の実デプロイ／eval ゲートCI の有効化**：`deploy.yml` / `eval-gate.yml` は用意済みだが、GCP 側の
  **WIF（鍵レス）設定＋リポジトリ変数**（`WIF_PROVIDER`/`DEPLOY_SA`/`GCP_PROJECT_ID` 等）が前提（未設定なら job は skip）。
  eval ゲートCI は採点に creds が要るため `google-adk[eval]`（`--extra eval`）＋ WIF が前提。
  （**main 比 baseline の保存・比較は実装済み**＝committed `eval/baseline.json`。WIF を有効化すれば nightly が
  初回採点して baseline を埋め、以後 PR が非劣化比較する。未採点（mean=null）の間は must_fix 0＋採点可能を緑とする。）
- **実様式1枚の入手による `write_draft`/`write_monthly_draft` 様式確定**（§18）：欄名対応は推論を含むため、
  実様式をヒアリングで入手して確定する（現状は越谷市様式系の汎用様式）。**実データ・現場ヒアリング依存で、コードだけでは閉じられない。**
- **現場の修正差分による eval ケースの質的拡充**（§12）：v0 は架空児 16 件。現場の👍👎・修正差分で「リアルな失敗」を
  足すのは現場との運用依存（PII 非コミットを守りつつ＝§14）。
- **rubric 文面の echo 安定化**（§12）：ADK は judge の echo テキストで rubric を照合するため、長い軸 rubric
  （axis_guideline_alignment）は judge の言い換えで照合漏れし一部ケースでその軸が欠落する（mustfix は不影響・
  軸平均は present のみ）。rubric 文面を短く echo 安定にする調整（要 live 再採点で確認）。
- **二階の堅牢化はスコープ外**（§8/§15）：大規模ルールの自動競合検出・多保育士調停はやらない（「閉じる1事例」で足りる）。
- ADK 2.3.0 で LoopAgent/SequentialAgent は deprecated（将来 Workflow へ）。設計（§6/§7）が前提とする API で
  2.3.0 の Workflow 代替は非公開のため v0 はこのまま使う（中期 TODO で移行）。
