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
| ③ 改善エージェント（§8） | `improver/`（別エントリ・手動起動） | 修正差分→指針更新を自走提案・競合は保育士に二択 | Agentic |
| 番人（最終）（§12） | `eval/`（cases/・judges/・`test_config.json`・`run_gate.py`） | 3軸 rubric で採点→main 比 非劣化＆must_fix 0 のみ取り込み | 決定的（CI） |

## harness 内訳（§5 物理マッピング）

| ファイル | 関数 | 役割 |
|---|---|---|
| `harness/router.py` | `DocTypeRouter` / `build_root_agent` | `state["doc_type"]` で日誌/月案パイプラインを振り分ける決定的分岐（root_agent の実体・既定＝保育日誌＝§3） |
| `harness/pipeline.py` | `build_document_pipeline` / `ApprovalGate` / `FinalizeAgent`(kind) / `is_approved` / `persist_visit_to_memory`(+`_should_persist_visit`) / `mark_caregiver_approved`(+`CAREGIVER_APPROVAL_KEY`) | 日誌：author → review_loop（reviewer→ApprovalGate で APPROVED 早期終了）→ finalize の順序制御。`after_agent_callback`＝**保育士の明示承認＋型成立**のときのみ来園を Memory Bank へ書き戻す（真の承認ゲート＝§9/§13） |
| `harness/monthly.py` | `MonthlyPrepAgent` / `build_monthly_pipeline` | 月案：前月日誌を child_id 別に決定的集計（L2 還流）→ 月案 author → review_loop → finalize(kind="monthly")（§3/§4/§10） |
| `harness/schema_check.py` | `validate_fields` / `validate_monthly_fields`(+`_required_tag_type`) | 必須欄＋年齢分岐（0–2＝3つの視点 / 3–5＝5領域）。日誌/月案で分岐の実体を共用 |
| `harness/draft.py` | `write_draft` / `write_monthly_draft` | pydantic（DiaryEntry/MonthlyPlan）→ 様式整形（10の姿/3つの視点/5領域タグ明示） |
| `harness/finalize.py` | `finalize_document` / `finalize_monthly_document` / `parse_draft_to_entry` / `parse_draft_to_plan` | author 出力（JSON）の復元 → 確定 validate/write（pipeline 末尾で実行する純ロジック・`_finalize` で共用） |
| `harness/aggregate.py` | `aggregate_by_child` / `prev_month_digest` / `format_digest_for_prompt` | 月⇔日の集積（child_id 別）と L2 還流の state 用 digest・人間可読テキスト。要約生成は月案 author |
| `harness/git_ops.py` | `apply_structured_edit` / `list_section_bullets` / `open_pr` | 構造化編集の適用・競合検出入力・branch/PR（プロダクトの git 操作。open_pr 既定 dry_run） |

## ツール（§6・4–8個のプリミティブ）

`tools/`（agent が呼ぶプリミティブ）: `recall_child_history`(子の前回までの像＝Memory Bank・`tool_context.search_memory`・未接続で降格) /
`search_guideline`(Vertex RAG・未設定で降格) / `read_policy`(育つ指針 HEAD) / `ask_caregiver`(HITL＝`LongRunningFunctionTool`) /
`validate_fields`(生成途中の自己点検)。配線は author（日誌）＝上記全部 / monthly_author（月案）＝`recall_child_history`・
`search_guideline`・`read_policy`・`ask_caregiver`（月案の確定 validation は harness の `validate_monthly_fields` が末尾実行・自己点検ツールは未配線）/
reviewer＝`read_policy`・`search_guideline`・`recall_child_history` のみ。
`validate_fields`・`write_draft` の決定的実体は harness（§5）で、最終の確定 validation・整形出力は harness が末尾で実行する＝
`write_draft` は agent tool ではない。`search_past_documents`(過去書類アーカイブ＝ローカル架空児記録ストア)は v0 では **agent に未配線**
（継続把握は `recall_child_history` に一本化＝§9。過去書類の引用が実需になれば復活。月⇄日集積は決定的に `aggregate_by_child`）。
improver 固有: `improver/tools.py`（`propose_policy_change`＋競合検出 / `run_eval`→`eval/run_gate.py`、
`open_pr` は harness 経由）。GCP 系（RAG/Memory）は config 未設定時に安全に降格する。

## メモリ3分類（§9）

| 対象 | 置き場 | 参照 |
|---|---|---|
| 子ども別 長期メモリ | Agent Engine Memory Bank（repo外） | 読み＝`recall_child_history`／書き戻し＝`persist_visit_to_memory`（pipeline の `after_agent_callback`・**保育士の明示承認＝`caregiver_approved` ＋型成立**でのみ発火＝真の承認ゲート）。配線は `--memory_service_uri=agentengine://<id>`（`config.memory_service_uri`／`server.py`）。未設定で降格 |
| 育つ文書作成指針 | git `knowledge/文書作成指針.md` | agent は読み取り（HEAD）／improver が編集（HITL+ゲート） |
| 静的ナレッジ（指針解説・10の姿） | Vertex RAG（`knowledge/保育所保育指針/` は gitignore のソース） | `search_guideline` |

## データフロー

```
観察メモ（音声/手入力）＋ state["doc_type"]（既定＝保育日誌）
  └─ harness: DocTypeRouter (root_agent) … doc_type で日誌/月案パイプラインを決定的に振り分け（§10）
       │
       ├─[日誌]─ document_pipeline (SequentialAgent)
       │    ├─ author (LlmAgent)  … 不足は ask_caregiver(HITL) / RAG・記録・子メモリを収集 / 指針準拠で
       │    │                        下書き＋DiaryEntry JSON → state["draft"]
       │    ├─ review_loop (LoopAgent: reviewer→approval_gate) … 指摘→state["review"]・APPROVED で早期終了
       │    └─ finalize(kind=diary) … 復元→validate_fields/write_draft → state["final_document"]/["validation"]、
       │                              awaiting_caregiver_approval=True（HITL）
       │
       └─[月案]─ monthly_plan_pipeline (SequentialAgent)
            ├─ monthly_prep (BaseAgent) … 前月日誌（state["prev_month_entries"]）を child_id 別に集計（L2 還流）
            │                              → state["prev_month_digest"]＋集計テキストを提示
            ├─ monthly_author (LlmAgent) … 前月集積＋子メモリから「前月の姿/評価反省」を要約・ねらい化 → state["draft"]
            ├─ review_loop （日誌と共用）
            └─ finalize(kind=monthly) … 復元→validate_monthly_fields/write_monthly_draft → state["final_document"]
       │
       └─[after_agent_callback] persist_visit_to_memory … **保育士の明示承認（caregiver_approved）＋型成立**の
                                  ときのみ来園を子の Memory Bank へ書き戻す（真の承認ゲート＝§9/§13。未配線/未承認は降格・保留）
出力（確定書類）＋ 保育士の修正差分 → eval（層B・run_gate＝3軸 rubric）→ improver が指針へ還元（HITL+ゲート）
```

## 実装状況（v0）と残課題

v0 で稼働する範囲は **保育日誌（0–2 個別）＋ 個別月案（0–2・L2 還流）**（§3「日誌先行 → 月案は集積に乗せる」）。
実装済み（決定的部分はテスト済み・GCP/LLM 非依存で稼働）:
- **doc_type 分岐 ＋ 月案パス ＋ L2 還流**：`DocTypeRouter`（root_agent）が doc_type で日誌/月案を振り分け、
  月案は `MonthlyPrepAgent` が前月日誌を child_id 別に決定的集計（`prev_month_digest`）→ `monthly_author` が
  要約・ねらい化 → `validate_monthly_fields`/`write_monthly_draft` で確定（§3/§4/§10）。`MonthlyPlan` スキーマ・
  月案決定論E2E（ルータ分岐/L2 還流/確定）まで実装・テスト済み。デモ入口＝`scripts/run_monthly.py`。
- レビュー APPROVED 早期終了（`ApprovalGate`／`is_approved`。判定は1行目の verdict＝prompts.py）。
- HITL 関門：`ask_caregiver`＝`LongRunningFunctionTool`、確定段の `awaiting_caregiver_approval` フラグ。
- 出力の最終 validation／整形（`FinalizeAgent(kind)`＋`harness/finalize.py`。日誌/月案で `_finalize` を共用）。
- `git_ops`（構造化編集の適用・競合入力・branch/PR＝既定 dry_run）、`improver`（propose＋競合検出／run_eval／open_pr）。
- **決定論E2E（結合テスト）**：`tests/test_e2e/`。`FakeLlm` 注入で日誌/月案パイプラインを実 ADK ランタイムに
  end-to-end で通し、連結・APPROVED 早期終了・巡回上限・確定3経路・HITL 不発火・**真の承認ゲートの書き戻し**・
  **L2 還流/ルータ分岐**を creds 不要・決定的に検証（品質採点は層B eval＝別系統）。起動は `/e2e` skill。
- **Memory Bank 配線（読み＋書き戻し）＋ 真の承認ゲート**：`config.memory_service_uri`（`agentengine://<id>`）→
  入口 `server.py`（ADK の `--memory_service_uri` 自動配線）。読み＝`recall_child_history`、書き戻し＝
  `persist_visit_to_memory`（`after_agent_callback`）。書き戻しは **保育士の明示承認（`caregiver_approved=True`＝
  `mark_caregiver_approved`）＋型成立**でのみ発火（型成立を承認の代理にしない＝§9/§13）。発火/保留/降格を決定論E2E で検証。
- **eval ゲートの本採点（3軸 rubric 配線）**：`eval/test_config.json` が ADK ネイティブの
  `rubric_based_final_response_quality_v1` に3軸（`axis_*`）＋must_fix（`mustfix_*`）を rubric として載せる。
  `eval/run_gate.py` が rubric 採点 → `aggregate_rubric_scores`（軸平均＝ケーススコア／mustfix の no＝違反）→
  `decide_gate`（main 比 非劣化 かつ must_fix 0）で **passed=True/False** を返す（採点不能時のみ None 降格＝偽の緑なし）。
  判定式の純関数は `tests/test_eval_gate.py` で LLM 非依存に検証。rubric 6件が config から評価器へロードされること、
  採点経路が全段（推論→評価→抽出）を例外なく走り creds 無で None 降格することを実機確認済み。
- **eval ケース**：`eval/cases/diary_0_2.evalset.json` を 16 件（架空児のみ・現場の多様な状況）に拡充。
  件数≥15・参照ドラフトが型を通る・実名なしを `tests/test_eval_cases.py` で決定論検査。
- **配信（層A）**：`Dockerfile`＋`.dockerignore`（`uvicorn server:app`・scale-to-zero。指針ファイルのみ同梱）、
  `.github/workflows/deploy.yml`（WIF で `gcloud run deploy --source .`）、`.github/workflows/eval-gate.yml`
  （nightly/手動・WIF で creds 採点）。決定論 CI（`ci.yml`）は従来どおり毎PR・creds 不要。
  docker build → コンテナ起動で `/docs` 200 を実機確認済み。

残課題（**外部リソース・実データ・各自 GCP 設定に依存。コードは降格付きで配線済み**＝コードだけでは閉じられない）:
- **各自 GCP のプロビジョニング＋ env 設定**（コード・スクリプトは実機検証済み）:
  - Vertex RAG corpus：`uv run python scripts/provision_rag_corpus.py --create`（新規 GCP は RagManagedDb を
    serverless へ REST 切替＋Vector Search API・埋め込みは `text-multilingual-embedding-002`）→ `.env` の `RAG_CORPUS`。
    未設定は `search_guideline` 降格。
  - Memory Bank：`uv run python scripts/provision_memory_bank.py --create`（生成モデル＋日本語/子の姿カスタマイズ）
    → `.env` の `AGENT_ENGINE_ID`。未設定は InMemory 降格。
  - 手順は `docs/ライブ実行手順.md`。Gemini/Vertex 自体は接続済み（ADC＋`GOOGLE_CLOUD_PROJECT`/`GEMINI_MODEL`）。
- **層A の実デプロイ／eval ゲートCI の有効化**：`deploy.yml` / `eval-gate.yml` は用意済みだが、GCP 側の
  **WIF（鍵レス）設定＋リポジトリ変数**（`WIF_PROVIDER`/`DEPLOY_SA`/`GCP_PROJECT_ID` 等）が前提（未設定なら job は skip）。
  eval ゲートCI は採点に creds が要るため `google-adk[eval]`（`--extra eval`）＋ WIF が前提。
  **main 比 非劣化の baseline 保存**（main 平均を記録して PR で比較）は次フェーズ（v0 は must_fix 0＋採点可能を緑とする）。
- **実様式1枚の入手による `write_draft`/`write_monthly_draft` 様式確定**（§18）：欄名対応は推論を含むため、
  実様式をヒアリングで入手して確定する（現状は越谷市様式系の汎用様式）。**実データ・現場ヒアリング依存で、コードだけでは閉じられない。**
- **現場の修正差分による eval ケースの質的拡充**（§12）：v0 は架空児 16 件。現場の👍👎・修正差分で「リアルな失敗」を
  足すのは現場との運用依存（PII 非コミットを守りつつ＝§14）。
- **二階の堅牢化はスコープ外**（§8/§15）：大規模ルールの自動競合検出・多保育士調停はやらない（「閉じる1事例」で足りる）。
- ADK 2.3.0 で LoopAgent/SequentialAgent は deprecated（将来 Workflow へ）。設計（§6/§7）が前提とする API で
  2.3.0 の Workflow 代替は非公開のため v0 はこのまま使う（中期 TODO で移行）。
