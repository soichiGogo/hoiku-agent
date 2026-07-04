# アーキテクチャ（設計のコード対応）

最終的な正は Obsidian vault の `設計/プロダクト方針.md` / `設計/エージェント設計.md`（repo 外）。
リポジトリ内の設計参照は `docs/設計コンテキスト.md`（開発ハンドオフ）。本ファイルはそれをコード構造に
対応づけた索引。構造を変えたら本ファイルと `CLAUDE.md` を同じ変更内で更新する。

## 3責務 ↔ コード（設計コンテキスト §5 責務境界）

| 責務 | コード | 役割 | 性質 |
|---|---|---|---|
| ① 型の保証（§5） | `harness/` | 必須欄・年齢分岐・順序・集積・doc_type分岐・指針カードストア。決定ロジックの唯一実装 | 決定的 |
| ② 中身の決定・作成AI（§6） | `agents/author_agent.py`（日誌）/ `agents/monthly_author_agent.py`（月案）/ `agents/child_record_author_agent.py`（児童票・§19）＝単一 `LlmAgent`＋tools | 情報収集（Agentic RAG）・質問生成・「姿→ねらい/評価」変換・集積（前月/期間）の要約。児童票は**開示前提の肯定的・非断定的表現**も担う | Agentic |
| ② レビューAI（§7） | `agents/review_agent.py`（`LlmAgent`・日誌/月案/児童票で共用） | 別視点で点検（開示前提の表現観点含む）・APPROVED まで巡回（制御は harness） | Agentic |
| ③ 改善エージェント（§8） | `improver/`（別エントリ・手動起動） | 修正メモ→指針カードの追加/改訂を自走提案・**意味的競合を精査**し保育士の決定で**即反映**（番人＝意味的競合精査＋保育士決定） | Agentic |
| 品質回帰の番人（§12） | `eval/`（cases/・judges/・`test_config.json`・`run_gate.py`） | 3軸 rubric で採点→main 比 非劣化＆must_fix 0。**CI の品質回帰テスト専用（prompt/モデル/指針の変更を守る）。improver の取り込みには関与しない＝decouple** | 決定的（CI） |
| 配信UI（層A・§11） | `web/`（`routes.py`・`improver_stream.py`・`chohyo_pdf.py`・`fonts/`・`static/`＝`docflow.js`/`docedit.js`/`policy.js` 等） | 保育士向け配布 UI（`/app/`）。**4つ目の責務ではない presentation**：日誌/月案/児童票は ADK ネイティブ REST を直接駆動（自前 Runner なし）、確定下書きは**標準様式の見た目の編集フォーム**（`docedit.js`）で保育士が自由に編集→ `/api/finalize-edit` で harness が再検査・再整形。**現場でそのまま綴じる最終形＝園の帳票PDF**は `/api/export-pdf`（`chohyo_pdf.py`＝ReportLab・IPAex 埋め込み・確認印欄（担任/主任/園長）付き・描画のみ）。改善エージェント（指針を育てる＝`policy.js`）だけ SSE 中継 | 中継・描画 |

## harness 内訳（§5 物理マッピング）

| ファイル | 関数 | 役割 |
|---|---|---|
| `harness/router.py` | `DocTypeRouter` / `build_root_agent` | `state["doc_type"]` で日誌/月案/児童票パイプラインを振り分ける決定的分岐（root_agent の実体・既定＝保育日誌＝§3/§19） |
| `harness/pipeline.py` | `build_document_pipeline` / `build_authoring_loop` / `ApprovalGate` / `FinalizeAgent`(kind) / `is_approved` / `persist_visit_to_memory`(+`_should_persist_visit`) / `mark_caregiver_approved`(+`CAREGIVER_APPROVAL_KEY`) | 日誌：authoring_loop（[author→reviewer→ApprovalGate] を巡回・NEEDS_REVISION で author が再作成・APPROVED 早期終了）→ finalize の順序制御。FinalizeAgent は `final_document`（整形テキスト）に加え **`final_entry`（構造化エントリ dict）＋`final_doc_kind`** も state に残す（編集UIが欄ごとの編集フォームに描く）。`after_agent_callback`＝**保育士の明示承認＋型成立**のときのみ来園を Memory Bank へ書き戻す（真の承認ゲート＝§9/§13） |
| `harness/monthly.py` | `DigestPrepAgent`（旧 MonthlyPrepAgent を入出力キーで一般化） / `build_monthly_pipeline` | 月案：前月日誌を child_id 別に決定的集計（L2 還流）→ 月案 author の authoring_loop（日誌と共用・再作成）→ finalize(kind="monthly")（§3/§4/§10）。`DigestPrepAgent` は児童票（L3）と共用 |
| `harness/child_record.py` | `build_child_record_pipeline` | 児童票（§19）：期間日誌（state["period_entries"]）を `DigestPrepAgent`（period_prep）で決定的集計（L3 還流）→ state["period_digest"] → 児童票 author の authoring_loop（共用）→ finalize(kind="child_record") |
| `harness/schema_check.py` | `validate_fields` / `validate_monthly_fields` / `validate_child_record_fields`(+`_required_tag_type`) | 必須欄＋年齢分岐（0–2＝3つの視点 / 3–5＝5領域）。日誌/月案/児童票で分岐の実体を共用。日誌の生活記録必須は **0–2 のみ**（3–5 は任意＝全年齢対応・§19） |
| `harness/draft.py` | `write_draft` / `write_monthly_draft` / `write_child_record_draft` | pydantic（DiaryEntry/MonthlyPlan/ChildRecord）→ **標準様式テキスト**へ整形（ネット調査で裏取りした章立て・順序。日誌＝ヘッダ（記録日・天候・気温/組の任意欄）→本日のねらい→主な活動→個別の記録（姿＋生活記録＝0–2 常時/3–5 記入時のみ）→…、月案＝**養護2本柱（生命の保持/情緒の安定）→教育**の順、児童票＝ヘッダ（期・対象児）→発達の経過（領域別叙述）→配慮・特記→家庭連携→総合所見→次期に向けて＝§19）。10の姿/3つの視点/5領域タグ明示 |
| `harness/finalize.py` | `finalize_document` / `finalize_monthly_document` / `finalize_child_record_document` / `finalize_entry` / `parse_draft_to_entry` / `parse_draft_to_plan` / `parse_draft_to_child_record` | author 出力（JSON）の復元 → 確定 validate/write（pipeline 末尾で実行する純ロジック・`_finalize` で共用）。`finalize_entry(dict)` は**編集UI用**＝保育士が編集した entry を JSON 抽出を飛ばして直接 validate/write 再実行（kind=diary/monthly/child_record・決定的実体は harness に1つ＝web から中継）。日誌の **date（記録日）は harness が所有する決定的メタデータ**＝`doc_date` で復元前に注入し author 出力を上書き（LLM に日付を生成させない＝雛形 echo 耐性。clock を持たず純関数を保つため現在日付の解決は `pipeline.FinalizeAgent`） |
| `harness/aggregate.py` | `aggregate_by_child` / `prev_month_digest` / `format_digest_for_prompt`(label) | 日誌集積（child_id 別）の state 用 digest・人間可読テキスト。月案（L2＝前月）と児童票（L3＝期間）で共用（label で見出し切替）。要約生成は各 author |
| `harness/policy_store.py` | `load_book`/`load_book_meta`/`save_book` / `add_card`/`supersede_card`/`remove_card` / `render_to_text` / `find_exact_duplicate` / `card_view`/`history_view`/`book_view` / `store_status` | 育つ指針＝構造化カードストアの決定的 CRUD・完全重複ガード（安全網）・履歴・テキスト再生・API view。**指針編集の決定的実体はここに1つ**（improver/read_policy は薄いラッパ）。clock は外部注入。置き場は IO 節で解決＝明示 path ＞ `POLICY_STORE_URI`（**gs://＝Cloud Run 永続**。`load_book_meta` の generation → `save_book(if_generation=…)` の precondition で read-modify-write を楽観ロック・競合は fail-loud） ＞ ローカル `knowledge/文書作成指針.json`。**「回した証拠」＝カード内蔵の変更履歴（decided_by 含む・GCS はオブジェクトバージョニング併用）** |
| `harness/record_store.py` | `save_document` / `approve_document` / `list_documents` / `list_diary_entries` / `list_child_record_entries` / `list_children` / `touch_user` / `list_audit_events` / `store_status` | 書類アーカイブ＝確定書類・児童マスタ・監査証跡（Cloud SQL PostgreSQL・Phase 1）。本文 JSON（PG は JSONB）が SSOT・検索キーだけ列昇格（射影テーブルなし）・版管理（AI 確定/保育士編集を区別）・承認証跡（actor 自己申告）。**LLM もパイプラインも呼ばない**（フロント→web API→ここの明示フロー）。`DATABASE_URL` 未設定は降格。表示名→children.id（UUID）解決の唯一の境界。スキーマ適用＝Alembic（repo root `migrations/`・`uv run alembic upgrade head`） |

## ツール（§6・4–8個のプリミティブ）

`tools/`（agent が呼ぶプリミティブ）: `recall_child_history`(子の前回までの像＝Memory Bank・`tool_context.search_memory`・未接続で降格) /
`search_guideline`(Vertex RAG・未設定で降格) / `read_policy`(育つ指針 HEAD) / `ask_caregiver`(HITL＝`LongRunningFunctionTool`) /
`validate_fields`(生成途中の自己点検)。配線は author（日誌）＝上記全部 / monthly_author（月案）・
child_record_author（児童票）＝`recall_child_history`・`search_guideline`・`read_policy`・`ask_caregiver`
（確定 validation は harness の `validate_monthly_fields`／`validate_child_record_fields` が末尾実行・自己点検ツールは未配線）/
reviewer＝`read_policy`・`search_guideline`・`recall_child_history` のみ。
`validate_fields`・`write_draft` の決定的実体は harness（§5）で、最終の確定 validation・整形出力は harness が末尾で実行する＝
`write_draft` は agent tool ではない。`search_past_documents`(過去書類アーカイブ＝ローカル架空児記録ストア)は v0 では **agent に未配線**
（継続把握は `recall_child_history` に一本化＝§9。過去書類の引用が実需になれば復活。月⇄日集積は決定的に `aggregate_by_child`）。
improver 固有: `improver/tools.py`（`read_policy_cards`／`propose_policy_card`＋意味的競合の申告＋完全重複ガード／
`commit_policy_card`＝保育士決定で即反映・`policy_store` を呼ぶ薄いラッパ）。
**run_eval/open_pr は撤去**（eval は CI 専用に decouple）。GCP 系（RAG/Memory）は config 未設定時に安全に降格する。

## メモリ3分類（§9）

| 対象 | 置き場 | 参照 |
|---|---|---|
| 子ども別 長期メモリ | Agent Engine Memory Bank（repo外） | 読み＝`recall_child_history`／書き戻し＝`persist_visit_to_memory`（pipeline の `after_agent_callback`・**保育士の明示承認＝`caregiver_approved` ＋型成立**でのみ発火＝真の承認ゲート）。配線は `--memory_service_uri=agentengine://<id>`（`config.memory_service_uri`／`server.py`）。未設定で降格 |
| 育つ文書作成指針 | 構造化カード。runtime の正＝`POLICY_STORE_URI`（gs://）設定時 **GCS オブジェクト**（バージョニング推奨・Cloud Run でも永続）／未設定はローカル `knowledge/文書作成指針.json`（git はシード） | agent は読み取り（`read_policy`＝`render_to_text`）／improver が**保育士の決定で即反映**（add/supersede・`policy_store`・GCS は generation 楽観ロック） |
| 静的ナレッジ（指針解説・10の姿） | Vertex RAG（`knowledge/保育所保育指針/` は gitignore のソース） | `search_guideline` |

## データフロー

```
観察メモ（音声/手入力）＋ state["doc_type"]（既定＝保育日誌）
  └─ harness: DocTypeRouter (root_agent) … doc_type で日誌/月案/児童票パイプラインを決定的に振り分け（§10/§19）
       │
       ├─[日誌]─ document_pipeline (SequentialAgent)
       │    ├─ authoring_loop (LoopAgent: author→reviewer→approval_gate を最大3巡)
       │    │    ├─ author (LlmAgent)  … 不足は ask_caregiver(HITL) / RAG・記録・子メモリを収集 / 指針準拠で
       │    │    │                        下書き＋DiaryEntry JSON → state["draft"]
       │    │    ├─ reviewer (LlmAgent) … 別視点で点検 → state["review"]
       │    │    └─ approval_gate … APPROVED で早期終了 / NEEDS_REVISION なら次巡で author が指摘点を再作成
       │    └─ finalize(kind=diary) … 記録日を解決（state["doc_date"]｜本日）→ 復元時に date 注入 →
       │                              validate_fields/write_draft → state["final_document"]（整形）/["final_entry"]（構造化）/["validation"]、
       │                              awaiting_caregiver_approval=True（HITL）
       │       └─[編集UI] web が final_entry を標準様式の編集フォームに描画 → 編集 → /api/finalize-edit
       │                  （finalize_entry で再 validate/write）→ state 反映 → 承認（caregiver_approved）
       │
       └─[月案]─ monthly_plan_pipeline (SequentialAgent)
            ├─ monthly_prep (DigestPrepAgent) … 前月日誌（state["prev_month_entries"]）を child_id 別に集計（L2 還流）
            │                              → state["prev_month_digest"]＋集計テキストを提示
            ├─ authoring_loop （日誌と共用: monthly_author→reviewer→approval_gate を巡回・再作成）
            │    └─ monthly_author (LlmAgent) … 前月集積＋子メモリから「前月の姿/評価反省」を要約・ねらい化 → state["draft"]
            └─ finalize(kind=monthly) … 復元→validate_monthly_fields/write_monthly_draft → state["final_document"]
       │
       └─[児童票]─ child_record_pipeline (SequentialAgent・§19)
            ├─ period_prep (DigestPrepAgent) … 期間日誌（state["period_entries"]）を child_id 別に集計（L3 還流）
            │                              → state["period_digest"]＋集計テキストを提示
            ├─ authoring_loop （共用: child_record_author→reviewer→approval_gate を巡回・再作成）
            │    └─ child_record_author (LlmAgent) … 期間集積＋子メモリから「発達の経過/総合所見」を領域別に叙述
            │                                        （開示前提＝肯定的・非断定的表現） → state["draft"]
            └─ finalize(kind=child_record) … 復元→validate_child_record_fields/write_child_record_draft → state["final_document"]
       │
       └─[after_agent_callback] persist_visit_to_memory … **保育士の明示承認（caregiver_approved）＋型成立**の
                                  ときのみ来園を子の Memory Bank へ書き戻す（真の承認ゲート＝§9/§13。未配線/未承認は降格・保留）
出力（確定書類）＋ 保育士の修正メモ → 改善エージェント（別エントリ）が指針カードを提案 → 意味的競合は
                                  保育士に比較相談 → 保育士の決定で即反映（policy_store・「回した証拠」＝カード履歴）
  ［別系統］eval（層B・run_gate＝3軸 rubric）＝CI の品質回帰テスト（prompt/モデル/指針の変更を守る・improver とは decouple）
```

## 実装状況（v0）と残課題

v0 で稼働する範囲は **保育日誌 ＋ 個別月案（L2 還流）＋ 児童票（期ごとの保育経過記録・L3 還流）**・
**全年齢（0–2/3–5）**（§3「日誌先行 → 月案は集積に乗せる」＋ §19「ヒアリング反映 2026-07＝主戦場を
蓄積の下流再構成へ・集積階層 日誌→月案→児童票→（将来）要録」）。
実装済み（決定的部分はテスト済み・GCP/LLM 非依存で稼働）:
- **doc_type 分岐 ＋ 月案パス ＋ L2 還流**：`DocTypeRouter`（root_agent）が doc_type で日誌/月案/児童票を振り分け、
  月案は `DigestPrepAgent`（monthly_prep）が前月日誌を child_id 別に決定的集計（`prev_month_digest`）→ `monthly_author` が
  要約・ねらい化 → `validate_monthly_fields`/`write_monthly_draft` で確定（§3/§4/§10）。`MonthlyPlan` スキーマ・
  月案決定論E2E（ルータ分岐/L2 還流/確定）まで実装・テスト済み。デモ入口＝`scripts/run_monthly.py`。
- **児童票パス ＋ L3 還流（§19）**：`ChildRecord`/`DevelopmentNote` スキーマ（期・発達の経過＝領域別叙述・
  配慮特記・家庭連携・総合所見・次期に向けて。越谷市公式様式＋実務解説で裏取りした③層＝叙述式経過記録のみを
  生成対象に。原簿・発達チェックリストは AI 外）。`DigestPrepAgent`（period_prep・`period_entries`→`period_digest`）→
  `child_record_author`（**開示前提の肯定的・非断定的表現**を instruction で担保・reviewer にも観点追加）→
  finalize(kind="child_record")。E2E（ルータ分岐/L3 還流/確定/降格）・evalset 6件まで実装・テスト済み。
  デモ入口＝`scripts/run_child_record.py`。期制（月次/3期/4期）の設定化は園差＝残課題（§18 と同枠）。
  **帳票PDF は年間マトリクス様式（実様式準拠）**：A4 横・行＝領域（0–2:3視点/3–5:5領域＋その他）×列＝4期の
  年間1枚。今回の期の列に加え、**同じ子・同じ年度の過去期の列は書類アーカイブ（record_store）の保存済み
  児童票から自動で埋める**（`/api/export-pdf` が `list_child_record_entries` で引き、列割当は
  `chohyo_pdf.assign_period_columns`＝純関数・今回の entry が常に優先・年度違い/期不明/別児は除外。
  アーカイブ未接続/該当なしは今回の期のみ＝空欄の罫線で手書き追記可）。身長・体重は
  原簿系の任意欄（`ChildRecord.height_cm/weight_kg`・**AI は生成しない**＝プロンプトで創作禁止・保育士が
  編集フォームで記入・過去期の値も各期の児童票から出す）。
- **全年齢対応（§19）**：0–2 限定を解除。年齢分岐は従来の `_required_tag_type`（0–2＝3つの視点/3–5＝5領域）を
  全書類で共用し、日誌の生活記録必須は 0–2 のみに限定（3–5 は任意＝整形/帳票も記入時のみ）。プロンプト・UI
  （年齢帯チップ・3–5 仮名児/サンプル）も全年齢化。AgeBand の 0/1–2 分割は v0 簡略化を維持（domain.py 注記）。
- レビュー巡回（`build_authoring_loop`＝[作成→レビュー→ApprovalGate]）：NEEDS_REVISION で作成AIが指摘点を
  再作成し、APPROVED 早期終了（`ApprovalGate`／`is_approved`。判定は1行目の verdict＝prompts.py）。再質問しない
  revision mode・date 等の機械的メタを指摘させない注意書きは prompts.py。
- HITL 関門：`ask_caregiver`＝`LongRunningFunctionTool`、確定段の `awaiting_caregiver_approval` フラグ。
- **標準様式への準拠（ネット調査で裏取り）**：`write_draft`/`write_monthly_draft` を 0–2 個別の標準様式へ（章立て・順序・
  **養護2本柱の分離**・**個別の生活記録**＝食事/睡眠/排泄/機嫌体調・本日のねらい・月齢・養護→教育の順）。制度用語2件の
  文言誤りも告示準拠に是正（3つの視点「健やかに伸び伸びと育つ」・10の姿「数量や図形、標識や文字などへの関心・感覚」）。
  `LifeRecord` スキーマ＋年齢分岐は `validate_*`/`write_*`/E2E/eval まで同調・テスト済み。
- **保育士の編集UI（標準様式の見た目）**：`FinalizeAgent` が `final_entry`（構造化）も state に出し、`docedit.js` が欄ごとの
  編集フォームに描画→ `/api/finalize-edit`（`finalize_entry` 中継）で再 validate/整形→承認（`/api/form-meta` がタグ語彙の SSOT）。
- 出力の最終 validation／整形（`FinalizeAgent(kind)`＋`harness/finalize.py`。日誌/月案/児童票で `_finalize` を共用）。
- **育つ指針＝構造化カード（§8 v1）**：`policy_store`（決定的 CRUD/render/完全重複ガード/履歴＝「回した証拠」・decided_by 含む）。`improver` は4ツール（`read_policy_cards`→`propose_policy_card`＝意味的競合の申告→`ask_caregiver`＝比較相談→`commit_policy_card`＝保育士決定で即反映）。eval は取り込みから decouple（CI 専用）。
- **育つ指針の外部永続化（GCS）**：`POLICY_STORE_URI`（`gs://<bucket>/文書作成指針.json`）設定時、`policy_store` の IO が GCS を読み書きし **Cloud Run のコンテナFS 揮発（再起動で即反映が消える）を解消**。read-modify-write は `load_book_meta` の generation → `save_book(if_generation=…)` の precondition で楽観ロック（競合は `commit_policy_card` が rejected へ変換＝黙って上書きしない）。`store_status` は GCS 設定時 "persistent"／到達不能 "unavailable" を正直に返す。未設定はローカル降格（依存追加なし＝google-cloud-storage は aiplatform の推移依存。フェイク Blob で creds 不要にテスト済み）。
- **決定論E2E（結合テスト）**：`tests/test_e2e/`。`FakeLlm` 注入で日誌/月案/児童票パイプラインを実 ADK ランタイムに
  end-to-end で通し、連結・APPROVED 早期終了・**NEEDS_REVISION での再作成（2枚目が確定）**・巡回上限・確定3経路・
  HITL 不発火・**真の承認ゲートの書き戻し**・**L2/L3 還流・ルータ分岐（日誌/月案/児童票）**を creds 不要・決定的に検証（品質採点は層B eval＝別系統）。起動は `/e2e` skill。
- **Memory Bank 配線（読み＋書き戻し）＋ 真の承認ゲート**：`config.memory_service_uri`（`agentengine://<id>`）→
  入口 `server.py`（ADK の `--memory_service_uri` 自動配線）。読み＝`recall_child_history`、書き戻し＝
  `persist_visit_to_memory`（`after_agent_callback`）。書き戻しは **保育士の明示承認（`caregiver_approved=True`＝
  `mark_caregiver_approved`）＋型成立**でのみ発火（型成立を承認の代理にしない＝§9/§13）。発火/保留/降格を決定論E2E で検証。
- **セッション永続化の配線（Cloud Run のインスタンス跨ぎ）**：`config.session_service_uri`（`agentengine://<id>`＝
  子ども長期記憶と同じ Agent Engine を共有セッションストアに流用）→ 入口 `server.py`（ADK が
  `VertexAiSessionService` を自動構築）。未指定だと ADK は InMemorySessionService＝各インスタンスのメモリ内で、
  Cloud Run（複数インスタンス＋scale-to-zero でメモリ揮発）だと作成セッションが別インスタンス／再起動で失われ
  `/apps/.../sessions/{id}` が 404 になる（ローカル単一プロセスでは顕在化しない）。memory と同じく
  `AGENT_ENGINE_ID` 未設定は InMemory 降格（§9：ADK ネイティブに委ね自前 Runner を組まない）。
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
- **eval ケース**：`eval/cases/diary_0_2.evalset.json` 16 件 ＋ `eval/cases/child_record.evalset.json` 6 件（§19・session_input で doc_type/期間日誌を seed・開示前提の参照ドラフト）＝計 22 件（実在しない仮名ロスターのみ・現場の多様な状況）。
  子どもは現場の日誌に寄せた仮名（下の名前＋ちゃん/くん）＋月齢・数量化した生活記録・具体的な姿で、`tests/test_eval_cases.py`
  の `_FICTIONAL_ROSTER` allowlist が実名/未知名の混入を機械的に落とす（§14）。
  件数≥15・参照ドラフトが型を通る・実名なしを `tests/test_eval_cases.py` で決定論検査。
- **配信（層A）**：`Dockerfile`＋`.dockerignore`（`uvicorn server:app`・scale-to-zero。指針ファイル＋`eval/baseline.json` のみ同梱）、
  `.github/workflows/deploy.yml`（WIF で `gcloud run deploy --source .`）、`.github/workflows/eval-gate.yml`
  （nightly/手動・WIF で creds 採点）。決定論 CI（`ci.yml`）は従来どおり毎PR・creds 不要。
  docker build → コンテナ起動で `/docs` 200 を実機確認済み。
- **保育士向け配布 UI（`web/`・B-full）**：`server.py` が `register_web_ui(app)` で `get_fast_api_app` に同居させる。
  保育士 SPA＝`/app/`（`/` も着地）、dev UI＝`/dev-ui/`、自前 API＝`/api/*`。日誌/月案/児童票はフロントが ADK ネイティブ REST
  （`/run_sse`・session 作成で月案 seed・`PATCH` 承認・`function_response` で HITL 再開）を直接駆動（自前 Runner なし＝§9）。
  **確定下書きは標準様式の見た目の編集フォーム（`docedit.js`）で保育士が欄ごとに自由に編集**でき（出欠/個別記録/教育ねらいは
  追加削除可・タグは年齢に応じ `/api/form-meta` の Enum 語彙から多選択・記録日/対象月は read-only）、保存時に
  `/api/finalize-edit`（harness の `finalize_entry` 中継）で再 validate/整形→state へ反映、承認で公式記録にロック（型成立ゲートは編集後も有効）。
  **現場でそのまま綴じる最終形＝園の帳票PDF**：確定/編集後の `final_entry` を「帳票PDFをダウンロード」で保存できる（`/api/export-pdf`→
  `chohyo_pdf.render_pdf`＝ReportLab で A4 罫線帳票・日誌/月案/児童票・欄順は標準様式に一致・**描画のみで型検査は harness**）。**末尾に確認印欄
  （担任/主任/園長）を置き公式記録の体裁を満たす**。生活記録（食事/睡眠/排泄/機嫌・体調）の4列表は本文全幅で他行と罫線をそろえる
  （ReportLab の Table 既定 hAlign=CENTER によるズレを LEFT＋全幅で是正）。ヘッダは気温・組（`DiaryEntry` の任意欄）を記入時のみ添える。日本語は
  IPAex ゴシックを埋め込むため閲覧側の CJK フォントに依存せず化けない（Heisei CID 非埋め込みの空白化を回避）。生成は純 pip・
  システムライブラリ不要でフォントは同梱＝**Dockerfile 不変**。LLM 非課金なので非ゲート。§18「園の様式で出す一段」に対応（標準様式まで到達・特定園の欄差は現場依存で残課題）。
  **改善エージェント（指針を育てる）**は `improver_stream.py` が `build_improver_agent` を InMemoryRunner で SSE 駆動（別エントリ維持）し、
  `policy.js`（温かい1タブ）が「指針カード閲覧＋変更履歴／提案→意味的競合の比較相談→保育士決定で即反映」をライブに描く（`/api/policy`＝カード＋履歴＋store）。
  LLM を回す口（`/api/improve`）だけ `DEMO_PASSCODE` でゲート（配布リンクのコスト/濫用対策）。
  **実機検証済み（creds 有・gemini-2.5-pro＋Memory Bank）**：日誌 HITL 発火→`function_response` 再開→確定、月案 L2 還流、編集フォーム保存→再 validate。
  **指針を育てる（即反映）の live creds スモークは未実施**（非LLM面は検証済み）。非LLM面（配線・静的配信・コストゲート・`/api/policy` 形・
  `/` 着地・`form-meta`/`finalize-edit`）は `tests/test_web.py` で決定論検証。`web/CLAUDE.md` に規約。
- **IAP 認証の土台（Phase 3 着手・2026-07-05）**：`web/iap.py`（`verified_iap_email`＝`IAP_AUDIENCE` 設定時のみ
  `x-goog-iap-jwt-assertion` を IAP 公開鍵で署名検証・未設定/失敗は None＝fail-closed でヘッダを信用しない）＋
  `record_store.users`／`touch_user`（検証済み email の auto-provision・migration 0002・認可は持たない）＋
  routes の actor 解決（検証済み email ＞ 自己申告・`/api/config` に user_email）。**IAP 自体の有効化
  （`gcloud run services update --iap`・アクセス権付与・audience 設定）は運用判断＝未実施**（現行の公開デモ＋
  パスコード運用は不変。有効化しても DEMO_PASSCODE は非 IAP 面の防御として残せる）。決定論テストは
  `tests/test_web.py`（偽装ヘッダ無視・検証成功で actor 優先・失敗で自己申告降格）／`tests/test_harness/test_record_store.py`（touch_user）。
- **書類アーカイブ（Phase 1・本番運用ブラッシュアップ 2026-07）**：`harness/record_store`（Cloud SQL PostgreSQL・
  children/documents/document_versions/audit_events・Alembic）＋web 配線（`/api/records`・`/api/records/approve`・
  `/api/records/diary-entries`・`/api/children`・担当者名入力＝audit の actor 自己申告）。**確定/編集/承認が
  版管理つきで永続化**され（AI 確定と保育士編集を区別＝修正差分の一次データ）、**L2/L3 の seed（前月・期間の
  日誌）はアーカイブから自動取得**（web・scripts とも。未接続/該当なしはサンプルへ降格＝eval/CI は DB 非依存で不変）。
  `deploy.yml` は `CLOUDSQL_INSTANCE`（var）＋`DATABASE_URL`（secret）で任意配線。テストは sqlite で決定論
  （`tests/test_harness/test_record_store.py`・`tests/test_web.py`）。

残課題（**外部リソース・実データ・各自 GCP 設定に依存。コードは降格付きで配線済み**＝コードだけでは閉じられない）:
- **各自 GCP のプロビジョニング＋ env 設定**（コード・スクリプトは実機検証済み）:
  - Vertex RAG corpus：`uv run python scripts/provision_rag_corpus.py --create`（新規 GCP は RagManagedDb を
    serverless へ REST 切替＋Vector Search API・埋め込みは `text-multilingual-embedding-002`）→ `.env` の `RAG_CORPUS`。
    未設定は `search_guideline` 降格。
  - Memory Bank：`uv run python scripts/provision_memory_bank.py --create`（生成モデル＋日本語/子の姿カスタマイズ）
    → `.env` の `AGENT_ENGINE_ID`。未設定は InMemory 降格。
  - 育つ指針の GCS バケット：`gcloud storage buckets create`（バージョニング有効化＋実行SAへ当該バケットのみ
    `roles/storage.objectAdmin`）→ 現行 `knowledge/文書作成指針.json` を初回アップロード → `.env`／Cloud Run env の
    `POLICY_STORE_URI`。未設定はローカル降格（Cloud Run では揮発＝store_status が "ephemeral" を正直表示）。
    手順は `docs/ライブ実行手順.md`。
  - 書類アーカイブの Cloud SQL：`gcloud sql instances create`（PostgreSQL 16・db-f1-micro）→ Auth Proxy 経由で
    `uv run alembic upgrade head` → `.env`／Cloud Run の `DATABASE_URL`（＋`--add-cloudsql-instances`＝
    `deploy.yml` の `CLOUDSQL_INSTANCE`/`DATABASE_URL`）。未設定は降格（永続化なし・seed はサンプル）。
  - 手順は `docs/ライブ実行手順.md`。Gemini/Vertex 自体は接続済み（ADC＋`GOOGLE_CLOUD_PROJECT`/`GEMINI_MODEL`）。
    既定モデル `gemini-3.5-flash` は Vertex **global 専用**のため、生成だけ `MODEL_LOCATION`（既定 global）へ固定し、
    RAG/Memory は `GOOGLE_CLOUD_LOCATION`（regional）のまま分離する（`src/hoiku_agent/models.py`＝`build_model`）。
- **層A の実デプロイ／eval ゲートCI の有効化**：`deploy.yml` / `eval-gate.yml` は用意済みだが、GCP 側の
  **WIF（鍵レス）設定＋リポジトリ変数**（`WIF_PROVIDER`/`DEPLOY_SA`/`GCP_PROJECT_ID` 等）が前提（未設定なら job は skip）。
  eval ゲートCI は採点に creds が要るため `google-adk[eval]`（`--extra eval`）＋ WIF が前提。
  （**main 比 baseline の保存・比較は実装済み**＝committed `eval/baseline.json`。WIF を有効化すれば nightly が
  初回採点して baseline を埋め、以後 PR が非劣化比較する。未採点（mean=null）の間は must_fix 0＋採点可能を緑とする。）
- **特定園の実様式1枚による微調整**（§18）：`write_draft`/`write_monthly_draft` は**ネット調査で裏取りした 0–2 個別の
  標準様式**（章立て・順序・養護2本柱・生活記録・制度用語）に準拠済み。残るのは特定園の欄差（午睡ブレスチェック間隔欄の
  型化要否・家庭連携/食育/健康の分割粒度・0歳=3つの視点 vs 旧式 0歳5領域など）をヒアリングで確定する微調整のみ＝
  **現場依存で、コードだけでは閉じられない**（標準様式準拠まではコードで到達済み）。
- **現場の修正差分による eval ケースの質的拡充**（§12）：v0 は実在しない仮名ロスター 22 件（日誌16＋児童票6）。現場の👍👎・修正差分で「リアルな失敗」を
  足すのは現場との運用依存（PII 非コミットを守りつつ＝§14）。
- **rubric 文面の echo 安定化**（§12）：ADK は judge の echo テキストで rubric を照合するため、長い軸 rubric
  （axis_guideline_alignment）は judge の言い換えで照合漏れし一部ケースでその軸が欠落する（mustfix は不影響・
  軸平均は present のみ）。rubric 文面を短く echo 安定にする調整（要 live 再採点で確認）。
- **二階の堅牢化はスコープ外**（§8/§15）：大規模ルールの自動競合検出・多保育士調停はやらない（「閉じる1事例」で足りる）。
- ADK 2.3.0 で LoopAgent/SequentialAgent は deprecated（将来 Workflow へ）。設計（§6/§7）が前提とする API で
  2.3.0 の Workflow 代替は非公開のため v0 はこのまま使う（中期 TODO で移行）。
