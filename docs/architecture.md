# アーキテクチャ（設計のコード対応）

最終的な正は Obsidian vault の `設計/プロダクト方針.md` / `設計/エージェント設計.md`（repo 外）。
リポジトリ内の設計参照は `docs/設計コンテキスト.md`（開発ハンドオフ）。本ファイルはそれをコード構造に
対応づけた索引。構造を変えたら本ファイルと `CLAUDE.md` を同じ変更内で更新する。

## 3責務 ↔ コード（設計コンテキスト §5 責務境界）

| 責務 | コード | 役割 | 性質 |
|---|---|---|---|
| ① 型の保証（§5） | `harness/` | 必須欄・年齢分岐・順序・集積・doc_type分岐・指針カードストア。決定ロジックの唯一実装 | 決定的 |
| ② 中身の決定・作成AI（§6） | `agents/monthly_author_agent.py`（個別月案）/ `agents/class_monthly_author_agent.py`（クラス月案・園の実様式・§18）/ `agents/child_record_author_agent.py`（保育経過記録・§19）/ `agents/nursery_record_author_agent.py`（保育要録・§19・L4）＝単一 `LlmAgent`＋tools（**保育日誌の作成AI＝旧 `author_agent.py` は退役**＝日誌は手入力）。instruction は `agents/instructions.py` の InstructionProvider で**文書作成指針（scope 別・共通＋当該書類）＋集積（前月/期間/最終年度）を prompt 冒頭へ決定的に前置注入**（§5・harness の `render_for_doc`/`format_digest_for_prompt`／要録は `format_record_digest_for_prompt` を呼ぶ薄い組み立て） | 情報収集（Agentic RAG）・質問生成・「姿→ねらい/評価」変換・集積（前月/期間/最終年度）の要約。保育経過記録・保育要録は**開示前提の肯定的・非断定的表現**も担う（要録は小学校引継ぎ＝10の姿の活用・最終年度に至るまでの育ちを recall_child_history から叙述） | Agentic |
| ② レビューAI（§7） | `agents/review_agent.py`（`LlmAgent`・月案/クラス月案/保育経過記録/保育要録で共用） | 別視点で点検（開示前提の表現観点含む）・APPROVED まで巡回（制御は harness） | Agentic |
| ③ 改善エージェント（§8） | `improver/`（別エントリ・手動起動） | 修正メモ→指針カードの追加/改訂を自走提案・**意味的競合を精査**し保育士の決定で**即反映**（番人＝意味的競合精査＋保育士決定） | Agentic |
| 品質回帰の番人（§12） | `eval/`（cases/・judges/・`test_config.json`・`run_gate.py`） | 3軸 rubric で採点→main 比 非劣化＆must_fix 0。**CI の品質回帰テスト専用（prompt/モデル/指針の変更を守る）。improver の取り込みには関与しない＝decouple** | 決定的（CI） |
| 配信UI（層A・§11） | `web/`（`routes.py`・`improver_stream.py`・`chohyo_pdf.py`・`fonts/`・`static/`＝`docflow.js`/`docedit.js`/`policy.js`/`notation.js` 等） | 保育士向け配布 UI（`/app/`）。**4つ目の責務ではない presentation**。**上位4タブ＝書類作成／育てる／クラス・園児／書類管理**。**保育日誌は手入力フォーム**（`diaryform.js`＝クラスの在籍児を空欄で並べ AI を通さない・ヒアリング 2026-07）／月案（クラス月案）/保育経過記録/要録は ADK ネイティブ REST を直接駆動（自前 Runner なし）。**クラス・園児タブ**（`classes.js`）＝園の名簿管理（クラス定義＋園児登録/割当＝`/api/classes`）。確定下書きは**標準様式の見た目の編集フォーム**（`docedit.js`）で保育士が自由に編集→ `/api/finalize-edit` で harness が再検査・再整形。**現場でそのまま綴じる最終形＝園の帳票PDF**は `/api/export-pdf`（`chohyo_pdf.py`＝ReportLab・IPAex 埋め込み・確認印欄（担任/主任/園長）付き・描画のみ）。**Word 編集版＝園の実 Word 様式に流し込んだ .docx** は `/api/export-docx`（`docx_fill.py`＝python-docx・雛形は `web/templates/`・純pip・docx→PDF 変換はしない・対応 kind＝保育経過記録/クラス月案/月案/保育要録）。改善エージェント（指針を育てる＝`policy.js`）だけ SSE 中継。**表記ルール辞書（`notation.js`＝`/api/notation` の CRUD）**は保育士が表記辞書を追加/編集/削除（harness 中継のみ・書込はゲート）。**アップロード取込（`records.js`＝「書類を見る」タブ）**は既存ファイル（PDF/Word/Excel）を種別フォルダから取り込み、`/api/parse-upload`（`upload_extract`＝format 変換＋`upload_parse`＝抽出AI駆動→`finalize_entry`）で既存スキーマ entry に解析→`docedit.js` で確認・修正→`/api/records`（`author_kind="imported"`）保存＝**以後 L2/L3/L4 seed として参照される**。**「書類を見る」タブは読取専用でなく、アーカイブ済み書類も編集・（再）承認できる**（`renderDetail` の「編集する／承認する」→`docedit.js`→`/api/finalize-edit`→`/api/records`〔`author_kind="caregiver"`・新版〕・承認は失効し再承認可）。外から特定書類を編集モードで開く `openDoc(id,{edit,focus})` を公開＝**クラス月案作成時に前月日誌で評価・反省が未記入のものを検出（`/api/records/diary-meta`）→「N/D を記入」チップで書類管理タブへジャンプし当該日誌の評価欄へフォーカス**（`app.js` の `checkPrevMonthEvaluations`／`switchTab`・生成はブロックしない・決定B/決定A）。**確定/承認画面・アーカイブ詳細に 👍👎＋ひとことの軽量フィードバック導線**（`feedback.js`）＝送信で文書＋版に紐付け保存（`/api/records/feedback`）、ひとことがあれば「この気づきを指針に活かす」で**その場（インライン）に改善エージェントを展開**（`policy.js` の `makePolicy` を再インスタンス化＝`/api/improve` の `feedback` を実値化）＝書類作成を通して「回す」が進む（doc kind→scope は `scopes.js` の `POLICY_SCOPE_OF` を単一ソースに解決） | 中継・描画 |
| インフラ基盤（IaC・§11） | `infra/`（Terraform）＋`.github/workflows/terraform.yml` | **プラットフォーム基盤を宣言化**＝API 有効化/SA・IAM/WIF・Cloud SQL（instance/db）・Secret の器・DNS ゾーン+レコード・Cloud Run ドメインマッピング・Artifact Registry。稼働実体は `imports.tf` で無停止採り込み（plan 差分ゼロを作ってから運用）。**Cloud Run サービス本体（image/env/revision）は `deploy.yml` 所有＝Terraform は import/所有しない境界**。CI＝PR で `plan`／main で `apply`（Environment `infra-prod` の手動承認・WIF で専用 `tf-admin` SA 借用）。**範囲外（`infra/README.md`）**＝請求予算（billing 権限を CI に渡さない）/ Google Sign-In OAuth クライアントのコンソール登録 / Cloud SQL ユーザー・パスワード / Secret の値 / RAG corpus・Memory Bank（TF 非対応＝`scripts/provision_*.py`）。責務ではない基盤の宣言化（初回のみローカル owner で bootstrap） | 宣言的（IaC） |

## harness 内訳（§5 物理マッピング）

| ファイル | 関数 | 役割 |
|---|---|---|
| `harness/router.py` | `DocTypeRouter` / `build_root_agent` | `state["doc_type"]` で月案/クラス月案/保育経過記録/保育要録パイプラインを振り分ける決定的分岐（root_agent の実体・**既定＝クラス月案**＝§18）。**保育日誌は AI 生成を退役**（ヒアリング 2026-07：日誌は手入力＝web で AI を通さない）したためルータに載らない |
| `harness/pipeline.py` | `build_authoring_loop` / `ApprovalGate` / `FinalizeAgent`(kind) / `is_approved` / `persist_visit_to_memory`(+`_should_persist_visit`) / `mark_caregiver_approved`(+`CAREGIVER_APPROVAL_KEY`) | 作成パイプラインの**共用機構**（月案/クラス月案/保育経過記録/保育要録が使う）。authoring_loop（[author→reviewer→ApprovalGate] を巡回・NEEDS_REVISION で author が再作成・APPROVED 早期終了）→ finalize の順序制御（文書作成指針は author/reviewer の InstructionProvider＝`agents/instructions.py` が prompt 冒頭へ前置注入するので pipeline に prep 段は無い＝§5）。FinalizeAgent は `final_document`（整形テキスト）に加え **`final_entry`（構造化エントリ dict）＋`final_doc_kind`** も state に残す（編集UIが欄ごとの編集フォームに描く）。`kind` は monthly/class_monthly/child_record/nursery_record を切替（diary は finalize_entry で手入力保存＝web）。`after_agent_callback`＝**保育士の明示承認＋型成立**のときのみ来園を Memory Bank へ書き戻す（真の承認ゲート＝§9/§13）。**旧 `build_document_pipeline`（保育日誌の AI 生成）は退役** |
| `harness/monthly.py` | `DigestPrepAgent`（旧 MonthlyPrepAgent を入出力キーで一般化・**state-only イベント**・`uncovered_by_key`＝保育経過記録に未反映の日誌へ限定するフィルタ〔クラス月案のみ・**児童別境界**＝`record_store.covered_until_by_child`〕） / `build_monthly_pipeline` | 月案：前月日誌を child_id 別に決定的集計（L2 還流）→ state["prev_month_digest"] に **content なしの state-only イベント**で載せる（前月集積は monthly_author の InstructionProvider が prompt へ整形注入・§10。content を持たせないのは eval judge が非LLM先頭段を採点不能にするのを避けるため＝§12）→ authoring_loop（日誌と共用・再作成）→ finalize(kind="monthly")。`DigestPrepAgent` は保育経過記録（L3）・クラス月案（未反映日誌）と共用 |
| `harness/class_monthly.py` | `ClassPlanPrepAgent`（自己履歴の state-only prep） / `build_class_monthly_pipeline` | クラス月案（園の実様式＝月間指導計画・§18・**依存モデル 2026-07**）：入力3系統＝① クラス児童の保育経過記録すべて（`RecordDigestPrepAgent` 共用・class_record_entries→class_records_digest）② それまでのクラス月案すべて（`ClassPlanPrepAgent`・past_class_plans→class_plan_digest＝計画の連続性）③ **保育経過記録に未反映の期間**の日誌（`DigestPrepAgent` 共用・class_diary_entries→class_diary_digest・`uncovered_by_key` で①から**児童別境界**を求め各児の未反映 note に限定＋**`reflections_key="class_diary_reflections"` で評価・反省をクラス一律 max 境界で集める＝決定B**）→ クラス月案 author の authoring_loop（共用）→ finalize(kind="class_monthly")。seed 合成は `record_store.class_monthly_seed_inputs`（scripts/web 共用）。個別月案（1児）と別 doc_type＝**文書の年齢帯単位**（Class 自体は年齢帯を持たず、名簿の生年月日＋対象年度から seed 対象を導出）。指針 scope は月案を流用。区分×領域グリッド（養護2本柱＋教育5領域）は 0–2/3–5 共通で3つの視点分岐を適用しない（様式忠実） |
| `harness/child_record.py` | `build_child_record_pipeline` | 保育経過記録（§19・**依存モデル 2026-07**）：期間日誌（state["period_entries"]）を `DigestPrepAgent`（period_prep）で決定的集計（L3 還流）→ state["period_digest"]、**前回までの保育経過記録すべて**（state["prev_record_entries"]＝全期・年度跨ぎ含む・作成対象の期は除外）を `RecordDigestPrepAgent`（prev_record_prep・要録と共用）で集計 → state["prev_records_digest"]（前期からの連続性の素） → 保育経過記録 author の authoring_loop（共用）→ finalize(kind="child_record") |
| `harness/youroku.py` | `RecordDigestPrepAgent` / `build_nursery_record_pipeline` | 保育要録（§19・L4・**依存モデル 2026-07＝それまでの保育経過記録すべて・全期・日誌は足さない**）：保育経過記録（state["record_entries"]）を `RecordDigestPrepAgent`（record_prep）で決定的集計（L4 還流＝日誌でなく**保育経過記録**を集める・実体は aggregate.child_record_digest）→ state["record_digest"] → 要録 author の authoring_loop（共用）→ finalize(kind="nursery_record")。`RecordDigestPrepAgent` は保育経過記録の「前回まで」・クラス月案の「クラス児童のこれまで」でも入出力キー差し替えで共用 |
| `harness/schema_check.py` | `validate_fields` / `validate_monthly_fields` / `validate_class_monthly_fields` / `validate_child_record_fields` / `validate_nursery_record_fields`(+`_required_tag_type`) | 必須欄＋年齢分岐（0–2＝3つの視点 / 3–5＝5領域）。日誌/月案/保育経過記録/保育要録で分岐の実体を共用（要録は年長＝5領域固定）。日誌の生活記録必須は **0–2 のみ**（3–5 は任意＝全年齢対応・§19）。**クラス月案は例外**＝様式が全年齢で5領域グリッドのため3つの視点分岐を課さず、グリッド各行のねらい＋0–2 の個人目標（≥1）を検査（§18） |
| `harness/draft.py` | `write_draft` / `write_monthly_draft` / `write_class_monthly_draft` / `write_child_record_draft` / `write_nursery_record_draft` ＋本文レンダラ（`_render_body`/`_render_section`/`_format_tagged_item`） | pydantic（DiaryEntry/MonthlyPlan/ClassMonthlyPlan/ChildRecord/NurseryRecord）→ **標準様式テキスト**へ整形。クラス月案は非線形の構造様式（保育経過記録マトリクスと同様 template_store は通さず GRID_ROWS を歩いて描く＝§18）。**本文レイアウト（章立て＝セクションの順序・見出しラベル・種別・出し分け）は `template_store` の様式テンプレート（データ）を歩いて描く**（§18＝園差をテンプレ編集で吸収）。ヘッダ合成と個別記録ブロック・生活記録・出欠サマリ等の構造描画はコード。順序＝日誌:本日のねらい→出欠→主な活動→個別の記録（姿＋生活記録＝0–2 常時/3–5 記入時のみ）→…、月案:**養護2本柱→教育**、保育経過記録:発達の経過→配慮特記→家庭連携→総合所見→次期、要録:最終年度の重点→個人の重点→保育の展開→特に配慮すべき事項→最終年度に至るまでの育ち（§19）。10の姿/3つの視点/5領域タグ明示 |
| `harness/template_store.py` | `load_template` / `find_template` / `book_view` / `load_book`/`load_book_meta`/`save_book` / `store_status` | **様式テンプレート＝本文レイアウトの宣言的データ**（`schemas/template.py` の DocTemplate/Section・閉じた種別語彙 text_block/text_inline/attendance/individual_notes/tagged_list/evaluation2）のストア。**3レンダラ共通で読む**＝テキスト整形（draft.py）・帳票PDF（chohyo_pdf の線形様式）・編集フォーム（docedit.js・`/api/doc-template`＝`book_view`）が本文セクションの順序/ラベルを取る（レイアウトの三重管理を解消・§18）。レイアウトのデータのみ（validation は持たない＝型の保証は schema_check・§5）。置き場は notation_store と同型＝明示 path ＞ `DATABASE_URL`（`template_books` 1行 JSONB・version 楽観ロック・migration 0005）＞ ローカル `knowledge/様式テンプレート.json`（git はシード）。**DB 到達不能／テーブル未整備（migration 0005 未適用）等の DB 障害は同梱シードへ降格して読む**（fail-loud だと全書類の write_*→finalize が落ちる＝本番 observed。レイアウトは常にシード代替可＝§5「降格safe」。`store_status` は DB を直接叩いて到達性を正直表示＝偽の "persistent" を出さない）。編集 UI は現状スコープ外（園差の実需で後続）。保育経過記録の帳票PDF は年間マトリクス様式（線形でない）ため対象外 |
| `harness/finalize.py` | `finalize_document` / `finalize_monthly_document` / `finalize_class_monthly_document` / `finalize_child_record_document` / `finalize_nursery_record_document` / `finalize_entry` / `parse_draft_to_entry` / `parse_draft_to_plan` / `parse_draft_to_class_plan` / `parse_draft_to_child_record` / `parse_draft_to_nursery_record` | author 出力（JSON）の復元 → **表記正規化**（`notation_store`＝validate/write の前・降格safe） → 確定 validate/write（pipeline 末尾で実行する純ロジック・`_finalize` で共用）。`finalize_entry(dict)` は**編集UI用**＝保育士が編集した entry を JSON 抽出を飛ばして直接 正規化→validate/write 再実行（kind=diary/monthly/class_monthly/child_record/nursery_record・決定的実体は harness に1つ＝web から中継）。表記の変更点は `FinalizedDocument.notation_changes`。日誌の **date（記録日）は harness が所有する決定的メタデータ**＝`doc_date` で復元前に注入し author 出力を上書き（LLM に日付を生成させない＝雛形 echo 耐性。clock を持たず純関数を保つため現在日付の解決は `pipeline.FinalizeAgent`） |
| `harness/notation_store.py` | `normalize_text` / `normalize_entry_dict` / `enabled_rules` / `add_rule`/`update_rule`/`remove_rule` / `load_book`/`load_book_meta`/`save_book` / `load_rules_or_empty` / `rule_view`/`book_view` / `store_status` | **ひらがな表記DX＝表記ルール辞書＋決定的な正規化器**（「子供→子ども」等の置換＋混入スペース除去）。正規化は**叙述系フィールド限定**（`NARRATIVE_FIELDS`）で仮名（child_id）/タグ/日付には触れない＝誤変換を型で防ぐ（§14）。CRUD は保育士が育てる編集辞書（web `/api/notation` から中継）。置き場は policy_store と同型＝明示 path ＞ `DATABASE_URL`（`notation_books` 1行 JSONB・version 楽観ロック・migration 0004）＞ ローカル `knowledge/表記ルール.json`（git はシード）。**育つ指針カード（agentic な勘所）とは別の道具＝決定的な表記の統一**（責務の線を混ぜない・§5）。clock は外部注入 |
| `harness/aggregate.py` | `aggregate_by_child` / `prev_month_digest` / `format_digest_for_prompt`(label) / `collect_reflections` / `format_reflections_for_prompt`(label) / `child_record_digest` / `format_record_digest_for_prompt`(label) / `class_plan_history_digest` / `format_class_plan_history_for_prompt`(label) | 日誌集積（child_id 別）の state 用 digest・人間可読テキスト。`format_digest_for_prompt` は author/reviewer の InstructionProvider（agents/instructions.py）が state の digest を prompt へ整形するのに使う（月案 L2＝前月／保育経過記録 L3＝期間・label で見出し切替）。**前月日誌の評価・反省は `collect_reflections`（日付順・(a)/(b) いずれか記入のみ）で別チャネルに集め、`format_reflections_for_prompt` で prompt へ前置＝クラス月案のみが使う（決定B＝PDCA の評価→次の計画。個別月案/保育経過記録は不使用）**＝評価は child_id 別でなく日次クラス所見なので aggregate_by_child に混ぜない。**要録（L4）は日誌でなくそれまでの保育経過記録すべて（全期）を集積**＝`child_record_digest`（期順・領域頻度・発達叙述・総合所見）＋`format_record_digest_for_prompt`（InstructionProvider が整形・保育経過記録の「前回まで」・クラス月案の「クラス児童のこれまで」とも共用＝label 切替）。**クラス月案の自己履歴は `class_plan_history_digest`（月順・目標・領域別ねらい・記入済みの月末評価）＋`format_class_plan_history_for_prompt`**（依存モデル 2026-07）。要約生成は各 author |
| `harness/policy_store.py` | `load_book`/`load_book_meta`/`save_book` / `add_card`/`supersede_card`/`remove_card` / `render_to_text`（全再生・UI/eval）/ `render_for_doc`（共通＋当該 scope のみ・履歴なし＝前置注入用） / `find_exact_duplicate` / `card_view`/`history_view`/`book_view` / `store_status` | 育つ指針＝構造化カードストアの決定的 CRUD・完全重複ガード（安全網）・履歴・テキスト再生・API view（**scope＝共通/保育日誌/月案/保育経過記録/保育要録**＝§19 で保育経過記録・保育要録を追加・render/view マップに相乗り）。**指針編集の決定的実体はここに1つ**（improver/tools は薄いラッパ）。前置注入は `render_for_doc`（agents/instructions.py の InstructionProvider が呼ぶ）・全体可視化は `render_to_text`（UI `/api/policy`）。clock は外部注入。置き場は IO 節で解決＝明示 path ＞ `DATABASE_URL`（**Cloud SQL＝書類アーカイブと同じ DB・Phase 2 で GCS から統合**。`policy_books` 1行に book 丸ごと JSONB＝カードを行へ射影しない。`load_book_meta` の version → `save_book(if_version=…)` の compare-and-swap で read-modify-write を楽観ロック・競合は fail-loud・行不在はローカルシードを返し version 0＝create-only） ＞ ローカル `knowledge/文書作成指針.json`（git はシード）。**「回した証拠」＝カード内蔵の変更履歴（decided_by 含む）** |
| `harness/db.py` | `Base` / `engine` / `reset_engine_cache` / `database_url` / **`is_missing_schema_error` / `missing_tables` / `schema_drift`（migration drift の観測）** | harness 共通の DB 接続基盤（engine キャッシュ・Declarative Base・JSONB variant）。record_store と policy_store が同じ `DATABASE_URL` を共有＝ドメインロジックは置かない。**加えてスキーマ整合の観測補助**＝`is_missing_schema_error`（テーブル/カラム不在をドライバ非依存に判定・record_store の `_write_error` が使う）／`schema_drift`（ORM 台帳 `Base.metadata` に対し実 DB に不足するテーブルを列挙・server.py 起動時に WARNING ログ＝§ prod-db-migration-drift の可視化）。ドメインでなく接続基盤の観測（決定的・creds 不要にテスト可） |

> 2026-07-10: `Class` は組名＋年度だけを保存する。年齢帯は固定属性でなく、在籍児の生年月日と対象年度の4月1日から導出する（migration 0009）。日誌・クラス月案などの `age_band` は、引き続き**書類**の属性である。
| `harness/record_store.py` | `Workspace` / `touch_user` / `save_document` / `approve_document` / `list_documents` / `get_document` / `request_workspace_deletion` / `process_due_deletion_requests` ほか | **Google user ごとの個人 workspace が認可境界**（migration 0011）。書類・園児・クラス・フィードバック・アーカイブ読取/集積を `workspace_id` で必ず絞る。既存データは所有者を推測せず「既存データ」workspace へ退避し、新規ログインからは見せない。削除依頼は本人確認済み session で受け付け、30日後に運営者コマンドが対象 workspace を消去する。 |

## ツール（§6・4–8個のプリミティブ）

`tools/`（agent が呼ぶプリミティブ）: `recall_child_history`(子の前回までの像＝Memory Bank・`tool_context.search_memory`・未接続で降格) /
`search_guideline`(Vertex RAG・未設定で降格) / `ask_caregiver`(HITL＝`LongRunningFunctionTool`) /
`validate_fields`(生成途中の自己点検)。配線は author（日誌）＝上記全部 / monthly_author（月案）・
child_record_author（保育経過記録）＝`recall_child_history`・`search_guideline`・`ask_caregiver`
（確定 validation は harness の `validate_monthly_fields`／`validate_child_record_fields` が末尾実行・自己点検ツールは未配線）/
reviewer＝`search_guideline`・`recall_child_history` のみ。
**文書作成指針は agent ツールでなく author/reviewer の InstructionProvider（`agents/instructions.py`）が prompt 冒頭へ前置注入する**
（doc_type は router で確定済み＝どの指針が要るかも確定済みなので、探索を LLM に委ねず harness の `render_for_doc` を決定的に注入する＝§5。旧 `read_policy` ツールは撤去）。
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
| 育つ文書作成指針 | 構造化カード。runtime の正＝`DATABASE_URL` 設定時 **Cloud SQL の `policy_books` 1行**（book 丸ごと JSONB・書類アーカイブと同じ DB＝Phase 2 統合・Cloud Run でも永続）／未設定はローカル `knowledge/文書作成指針.json`（git はシード＝DB 行不在時のフォールバックも兼ねる） | agent への提示＝author/reviewer の InstructionProvider（`agents/instructions.py`）が作る書類の scope で共通＋当該書類の勘所を prompt 冒頭へ前置注入（`render_for_doc`）／improver が**保育士の決定で即反映**（add/supersede・`policy_store`・version 楽観ロック） |
| 静的ナレッジ（指針解説・10の姿） | Vertex RAG（`knowledge/保育所保育指針/` は gitignore のソース） | `search_guideline` |

**（参考）表記ルール辞書（ひらがな表記DX）は "メモリ" ではない**：保育士が育てる決定的な表記統一の辞書で、
置き場は policy_books と同型（`DATABASE_URL` 設定時 Cloud SQL の `notation_books` 1行／未設定はローカル
`knowledge/表記ルール.json`・migration 0004）。参照は agent プロンプトでなく **harness が確定時（finalize）に
`notation_store.normalize_*` で決定的に適用**（叙述系フィールド限定）。編集は web `/api/notation`。
育つ指針カード（agentic な勘所）と表記ルール（決定的な表記）は役割が別＝混ぜない（§5）。

## データフロー

```
[保育日誌]＝手入力（AI を通さない・ヒアリング 2026-07）
  web: クラス選択（`/api/classes`）→ 在籍児 roster を空欄で並べた DiaryEntry を組み（`diaryform.js`）→
       docedit の標準様式編集フォームで保育士が共通欄＋児童ごとを手入力 → /api/finalize-edit
       （harness `finalize_entry`＝表記正規化→validate_fields→write_draft〔LLM 非依存〕）→ /api/records
       （`author_kind=caregiver`＝以後 L2/L3/L4 seed）→ 承認証跡（approveRecord）。ADK/root_agent は通らない。

観察メモ＋ state["doc_type"]（月案/クラス月案/保育経過記録/保育要録）＝AI 生成書類
  └─ harness: DocTypeRouter (root_agent) … doc_type で各パイプラインを決定的に振り分け（既定＝クラス月案・§10/§19）
       │
       └─[月案]─ monthly_plan_pipeline (SequentialAgent)  ※ 指針＋前月集積は InstructionProvider が prompt 冒頭へ前置
            ├─ monthly_prep (DigestPrepAgent) … 前月日誌（state["prev_month_entries"]）を child_id 別に集計（L2 還流）
            │                              → state["prev_month_digest"] に **state-only イベント**で格納（content 無し＝§12）
            ├─ authoring_loop （日誌と共用: monthly_author→reviewer→approval_gate を巡回・再作成）
            │    └─ monthly_author (LlmAgent) … 前月集積＋子メモリから「前月の姿/評価反省」を要約・ねらい化 → state["draft"]
            └─ finalize(kind=monthly) … 復元→表記正規化→validate_monthly_fields/write_monthly_draft → state["final_document"]
       │
       └─[クラス月案]─ class_monthly_pipeline (SequentialAgent・§18・園の実様式・依存モデル 2026-07)
            │                              ※ 指針(scope=月案)＋3集積＋振り返りは InstructionProvider が前置
            ├─ class_record_prep (RecordDigestPrepAgent) … ①クラス児童の保育経過記録すべて（state["class_record_entries"]・
            │                              全期・年度跨ぎ含む）を child_id 別に集計 → state["class_records_digest"]
            ├─ class_plan_prep (ClassPlanPrepAgent) … ②それまでのクラス月案すべて（state["past_class_plans"]）を
            │                              月順の履歴に集計（目標・ねらい・月末評価）→ state["class_plan_digest"]
            ├─ class_diary_prep (DigestPrepAgent) … ③保育経過記録に未反映の期間の日誌（state["class_diary_entries"]・
            │                              uncovered_by_key=①から児童別境界を求め各児の未反映 note に限定）を child_id 別に集計
            │                              → state["class_diary_digest"]＋評価・反省（class_diary_reflections＝決定B）
            │                              （いずれも content 無し state-only＝§12。seed 合成は record_store.class_monthly_seed_inputs）
            ├─ authoring_loop （共用: class_monthly_author→reviewer→approval_gate を巡回・再作成）
            │    └─ class_monthly_author (LlmAgent) … クラス全体のねらい・区分×領域グリッド（養護2本柱＋教育5領域）・0–2 は登場児ぶんの
            │                                        個人目標を生成（評価系欄は月末記入＝AI 非生成）→ state["draft"]
            └─ finalize(kind=class_monthly) … 復元→grid 正準化（model_validator）→表記正規化→validate_class_monthly_fields/
                                              write_class_monthly_draft → state["final_document"]（園フォーム様式）
       │
       └─[保育経過記録]─ child_record_pipeline (SequentialAgent・§19・依存モデル 2026-07)
            │                              ※ 指針＋期間集積＋前回まで集積は InstructionProvider が prompt 冒頭へ前置
            ├─ period_prep (DigestPrepAgent) … ①該当期間の日誌（state["period_entries"]）を child_id 別に集計（L3 還流）
            │                              → state["period_digest"] に **state-only イベント**で格納（content 無し＝§12）
            ├─ prev_record_prep (RecordDigestPrepAgent) … ②前回までの保育経過記録すべて（state["prev_record_entries"]・
            │                              全期・作成対象の期は除外）を集計 → state["prev_records_digest"]
            ├─ authoring_loop （共用: child_record_author→reviewer→approval_gate を巡回・再作成）
            │    └─ child_record_author (LlmAgent) … 期間集積＋前回までの記録＋子メモリから「発達の経過/総合所見」を
            │                                        領域別に叙述（前期からの連続性・開示前提＝肯定的・非断定的表現） → state["draft"]
            └─ finalize(kind=child_record) … 復元→表記正規化→validate_child_record_fields/write_child_record_draft → state["final_document"]
       │
       └─[保育要録]─ nursery_record_pipeline (SequentialAgent・§19・L4・年長のみ・依存モデル 2026-07＝日誌は足さない)
            ├─ record_prep (RecordDigestPrepAgent) … それまでの保育経過記録すべて（state["record_entries"]・全期・
            │                              年度跨ぎ含む）を child_id 別に集計（L4 還流＝日誌でなく保育経過記録を
            │                              集める・aggregate.child_record_digest）→ state["record_digest"]
            ├─ authoring_loop （共用: nursery_record_author→reviewer→approval_gate を巡回・再作成）
            │    └─ nursery_record_author (LlmAgent) … 全期集積（最終年度中心）＋子メモリ（入所時から）を「保育の展開/
            │                                        個人の重点/最終年度に至るまでの育ち」へ再構成（小学校引継ぎ＝開示前提・10の姿）→ state["draft"]
            └─ finalize(kind=nursery_record) … 復元→表記正規化→validate_nursery_record_fields/write_nursery_record_draft → state["final_document"]
       │
       └─[after_agent_callback] persist_visit_to_memory … **保育士の明示承認（caregiver_approved）＋型成立**の
                                  ときのみ来園を子の Memory Bank へ書き戻す（真の承認ゲート＝§9/§13。未配線/未承認は降格・保留）
出力（確定書類）＋ 保育士の修正メモ／**確定画面の 👍👎＋ひとこと**（`feedback.js`→`/api/records/feedback` で
                                  文書＋版に紐付け保存）→ 改善エージェント（別エントリ・確定画面インライン or 育てるタブ）が
                                  指針カードを提案（ひとことが一般化できる勘所のときだけ・特定固有なら「更新不要」で終える）→ 意味的競合は
                                  保育士に比較相談 → 保育士の決定で即反映（policy_store・「回した証拠」＝カード履歴）
  ［別系統］eval（層B・run_gate＝3軸 rubric）＝CI の品質回帰テスト（prompt/モデル/指針の変更を守る・improver とは decouple）
```

## 実装状況（v0）と残課題

v0 で稼働する範囲は **保育日誌 ＋ 個別月案（L2 還流）＋ 保育経過記録（期ごと・L3 還流）＋
保育要録（保育所児童保育要録・L4 還流＝それまでの保育経過記録すべての集積・年長のみ）**・**全年齢（0–2/3–5・要録は年長=5領域）**
（§3「日誌先行 → 月案は集積に乗せる」＋ §19「ヒアリング反映 2026-07＝主戦場を蓄積の下流再構成へ・
集積階層 日誌→月案（L2）→保育経過記録（期・L3）→要録（年・L4）＝全段実装済み」。**依存モデル（2026-07-07 確定）**＝保育経過記録:該当期間の日誌＋前回までの自己履歴すべて／クラス月案:クラス児童の保育経過記録すべて＋それまでのクラス月案すべて＋経過記録に未反映の期間の日誌／要録:それまでの保育経過記録すべて（全期・日誌は足さない）。「すべて」は年度跨ぎ可）。
実装済み（決定的部分はテスト済み・GCP/LLM 非依存で稼働）:
- **書類依存モデルの刷新（2026-07-07 確定）**：3書類の集積入力を「対応するクラス・児童の作成済み過去書類」
  ベースへ再定義した。①保育経過記録＝該当期間の日誌（従来）＋**前回までの保育経過記録すべて**
  （`prev_record_entries`→`prev_records_digest`・作成対象の期は `exclude_period` で除外）。②クラス月案＝
  **クラス児童の保育経過記録すべて＋それまでのクラス月案すべて＋保育経過記録に未反映の期間の日誌**
  （前月日誌ベース L2 を置換。未反映は**児童別境界**＝`record_store.covered_until_by_child`〔各児の期間終了日・解釈不能な期は
  寄与しない＝安全側〕・seed 合成＝`class_monthly_seed_inputs`・評価反省〔決定B〕は未反映日誌から継続）。
  ③要録＝それまでの保育経過記録すべて（実装は従来から全期＝「最終年度」表記の乖離を是正・日誌は足さない）。
  「すべて」は全期・年度跨ぎ可。集積は InstructionProvider の **digest spec 列**（`agents/instructions.py`）で
  書類ごとに複数系統を順に前置注入。クラス単位書類（日誌/クラス月案）の dedupe_key に年齢帯を追加
  （同日・別クラスの版混線を是正）。E2E/web/record_store テストで決定論検証済み。
- **保育日誌の手入力化＋AI 生成の退役＋クラス概念（2026-07-06・ヒアリング反映）**：日誌は「AI が観察メモから
  全生成」→「保育士がクラス単位で手入力する一次情報の蓄積口」へ位置づけ直した（ヒアリング＝日誌は自分の言葉で
  打つもの・AI 全生成は現場運用に合わない）。① **クラス（組）を一次エンティティ化**（`record_store.Class`＋
  `children.class_id`・migration 0007/0009・CRUD＝`list_classes`/`upsert_class`/`assign_child_to_class`/
  `list_children_in_class`・web `/api/classes`・新タブ「クラス・園児」＝`classes.js`。Class は組名＋年度だけを保存し、
  年齢帯は在籍児の生年月日と対象年度から導出）。② **日誌手入力フォーム**
  （`web/diaryform.js`＝クラスの在籍児を空欄で並べ、docedit の編集フォーム→`/api/finalize-edit`→`/api/records`
  〔`author_kind=caregiver`＝L2/L3/L4 seed として下流に流れる〕→承認証跡。ADK セッション不使用＝AI を通さない）。
  ③ **AI 日誌生成の退役**（`build_document_pipeline`／`build_author_agent`／`AUTHOR_INSTRUCTION` を撤去・router
  既定を保育日誌→クラス月案へ・日誌 eval 16件を撤去〔母集団が変わったため baseline を再採点＝mean=null〕・
  共用機構の E2E〔`test_pipeline_e2e`〕を保育経過記録パイプラインへ再ポイント）。共用機構（`build_authoring_loop`/
  `FinalizeAgent`/`persist_visit_to_memory`）と日誌の決定的検査・整形（`finalize_entry`/`validate_fields`/
  `write_draft`/notation/帳票PDF/docedit）は不変で流用。**留意：手入力日誌は ADK を通らないため Memory Bank
  書き戻し（`persist_visit_to_memory`）は発火しない**が、下流集積（月案 L2/経過記録 L3/要録 L4）はアーカイブから
  seed するため影響なし（`recall_child_history` だけ影響）。④ **校正AI（日本語チェック・言い換え提案）**：手入力後
  「日本語をチェック」で叙述文へ**提案のみ**返す＝AI は著者でなく校正者（`agents/proofreader_agent`＝別エントリ単一
  LlmAgent・`web/proofread`＝1パス駆動・`/api/proofread`＝ゲート・`schemas/proofread`）。提案は id→entry のパスへ写像し
  保育士が採否（自動書換なし・事実は変えない）。表記の機械的統一は notation が別途担う（役割分担・§5）。開示前提の観点は
  kind で出し分け（doc_type 非依存・diary 先行）。実 LLM ＋実ブラウザ E2E（入力→チェック→提案→採否→反映）を検証済み。
- **doc_type 分岐 ＋ 月案パス ＋ L2 還流**：`DocTypeRouter`（root_agent）が doc_type で月案/クラス月案/保育経過記録/保育要録を振り分け（既定＝クラス月案・**保育日誌は手入力＝ルータ外**）、
  月案は `DigestPrepAgent`（monthly_prep）が前月日誌を child_id 別に決定的集計（`prev_month_digest`）→ `monthly_author` が
  要約・ねらい化 → `validate_monthly_fields`/`write_monthly_draft` で確定（§3/§4/§10）。`MonthlyPlan` スキーマ・
  月案決定論E2E（ルータ分岐/L2 還流/確定）まで実装・テスト済み。デモ入口＝`scripts/run_monthly.py`。
- **クラス月案パス（園の実様式＝月間指導計画・L2 還流・§18）**：園が実際に使うクラス月案フォーム
  （`web/templates/monthly_*.docx`＝A4 横・区分×領域グリッド〔養護2本柱＋教育5領域〕＋0–2 の個人目標小表）を
  型にした `ClassMonthlyPlan`（`GRID_ROWS` を SSOT に grid を model_validator が正準7行へ決定的に整える）。
  個別月案（1児）と別 doc_type＝**文書の年齢帯単位**。入力は依存モデル 2026-07 の3系統（クラス児童の
  保育経過記録すべて＝RecordDigestPrepAgent／それまでのクラス月案すべて＝ClassPlanPrepAgent／経過記録に
  未反映の期間の日誌＝DigestPrepAgent・uncovered_by_key）→ `class_monthly_author`（クラス全体の
  ねらい・区分×領域グリッド・0–2 は登場児ぶんの個人目標を生成／評価系欄は月末記入＝AI 非生成）→
  finalize(kind="class_monthly")。seed 合成＝`record_store.class_monthly_seed_inputs`（scripts/web 共用）。0–2/3–5 とも様式は5領域グリッドで共通＝3つの視点分岐は課さない（様式忠実）。
  確認UIは**園の実様式ルック**（`docedit.js` の buildClassMonthly＝罫線の区分×領域グリッドをセル内テキストエリアで
  編集）＝保育士が普段の月案の感覚で確認・修正できる。帳票PDF（chohyo_pdf・A4 横で園フォーム再現）・Word 流し込み
  （docx_fill・園フォーム全欄）まで実装。決定論E2E（ルータ分岐/L2 クラス集積/確定/0–2 個人目標/3–5 個人目標なし/
  grid 正準化）・harness 単体・web（PDF/docx/finalize-edit）・record_store・notation までテスト済み。デモ入口＝
  `scripts/run_class_monthly.py`。**UI の「書類を作る」月案セグメントはクラス月案に一本化**（個別月案は
  バックエンド・アーカイブ閲覧で温存）。**「書類を見る」タブ・「育てる（指針を育てる）」タブも個別月案表記を
  クラス月案へ統合**（2026-07-06）＝アップロード取込は月案をクラス月案に一本化（下記）、指針スコープ「月案」の
  表示ラベルもクラス月案に統一（scope 値・card doc_type は不変）。クラス月案の evalset 追加は残課題（現場データ待ち）。
- **保育経過記録パス ＋ L3 還流（§19）**：`ChildRecord`/`DevelopmentNote` スキーマ（期・発達の経過＝領域別叙述・
  配慮特記・家庭連携・総合所見・次期に向けて。越谷市公式様式＋実務解説で裏取りした③層＝叙述式経過記録のみを
  生成対象に。原簿・発達チェックリストは AI 外）。`DigestPrepAgent`（period_prep・`period_entries`→`period_digest`）＋**前回までの保育経過記録すべて**
  （`prev_record_entries`→`prev_records_digest`＝RecordDigestPrepAgent 共用・作成対象の期は除外・依存モデル 2026-07）→
  `child_record_author`（**前期からの連続性**＋**開示前提の肯定的・非断定的表現**を instruction で担保・reviewer にも観点追加）→
  finalize(kind="child_record")。E2E（ルータ分岐/L3 還流/確定/降格）・evalset 6件まで実装・テスト済み。
  デモ入口＝`scripts/run_child_record.py`。期制（月次/3期/4期）の設定化は園差＝残課題（§18 と同枠）。
- **保育要録パス ＋ L4 還流（§19・集積階層の最終段）**：`NurseryRecord` スキーマ（全国統一様式の「保育に関する
  記録」＝最終年度の重点/個人の重点/保育の展開と子どもの育ち〔5領域/10の姿・DevelopmentNote 共用〕/特に配慮すべき
  事項/最終年度に至るまでの育ち。「入所に関する記録」＝就学先・保育期間は原簿系で AI 生成しない任意欄）。
  L4 の集積は **日誌でなくそれまでの保育経過記録すべて（全期・依存モデル 2026-07＝日誌は足さない）**を集める（`RecordDigestPrepAgent`（record_prep・`record_entries`→
  `record_digest`）＝実体は `aggregate.child_record_digest`）→ `nursery_record_author`（**小学校引継ぎ＝開示前提・
  10の姿の活用**を instruction で担保・最終年度に至るまでの育ちは `recall_child_history` から叙述・reviewer 共用）→
  finalize(kind="nursery_record")。年長（5歳児＝5領域）専用で年齢分岐は畳まれる（`_required_tag_type(3–5)` 流用）。
  E2E（ルータ分岐/L4 還流/確定/降格）・evalset 3件・帳票PDF まで実装・テスト済み。デモ入口＝`scripts/run_youroku.py`
  （それまでの保育経過記録すべてを seed＝アーカイブ `list_child_record_entries`〔全期〕接続時は取得・未接続はサンプル降格。
  複数年供給は依存モデル 2026-07 で解消＝全期を渡し最終年度中心の再構成は author の責務）。
  **帳票PDF は年間マトリクス様式（実様式準拠）**：A4 横・行＝領域（0–2:3視点/3–5:5領域＋その他）×列＝4期の
  年間1枚。今回の期の列に加え、**同じ子・同じ年度の過去期の列は書類アーカイブ（record_store）の保存済み
  保育経過記録から自動で埋める**（`/api/export-pdf` が `list_child_record_entries` で引き、列割当は
  `chohyo_pdf.assign_period_columns`＝純関数・今回の entry が常に優先・年度違い/期不明/別児は除外。
  アーカイブ未接続/該当なしは今回の期のみ＝空欄の罫線で手書き追記可）。身長・体重は
  原簿系の任意欄（`ChildRecord.height_cm/weight_kg`・**AI は生成しない**＝プロンプトで創作禁止・保育士が
  編集フォームで記入・過去期の値も各期の保育経過記録から出す）。
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
- 出力の最終 validation／整形（`FinalizeAgent(kind)`＋`harness/finalize.py`。日誌/月案/保育経過記録で `_finalize` を共用）。
- **育つ指針＝構造化カード（§8 v1）**：`policy_store`（決定的 CRUD/render/完全重複ガード/履歴＝「回した証拠」・decided_by 含む・**scope＝共通/保育日誌/月案/保育経過記録/保育要録**）。`improver` は4ツール（`read_policy_cards`→`propose_policy_card`＝意味的競合の申告→`ask_caregiver`＝比較相談→`commit_policy_card`＝保育士決定で即反映）。eval は取り込みから decouple（CI 専用）。
- **ひらがな表記DX＝表記正規化（決定的・2026-07-05）**：`notation_store`（表記ルール辞書＋正規化器）を新設し、`finalize`（確定処理）が validate/write の前に `normalize_entry_dict` を決定的に適用する。「子供→子ども」「友達→友だち」等の置換＋混入スペース除去を**取りこぼしなく一貫適用**（保育士が調べる余裕がなくても全員が助かる＝ヒアリング 2026-07）。**叙述系フィールド限定**で仮名（child_id）/タグ/日付には触れない（誤変換を型で防ぐ・§14）。保育士は web「表記ルール」タブ（`/api/notation` の CRUD）で辞書を追加/編集/削除でき、暴発ルールは `enabled=False` で止められる（silent lock しない）。置き場は policy_store と同型（`notation_books` 1行 JSONB・migration 0004・未設定はローカル `knowledge/表記ルール.json` シード・降格safe）。**育つ指針カード（soft な勘所）とは別の道具＝決定的な表記の統一**（§5 の線を混ぜない）。単体・DB round-trip・finalize 経路・web CRUD・実ブラウザ CRUD をテスト/検証済み。
- **保育経過記録 scope の相乗り（§19・2026-07-05）**：`PolicyScope.保育経過記録` を追加し、保育経過記録作成の暗黙知（開示前提の肯定的・非断定的表現 等）を作成AI・レビューAI が参照し（harness が前置注入）保育士が improver UI で育てられるようにした。新ツールは作らず既存の指針カード機構（render/view/improver）を拡張＝二重実装しない。seed に保育経過記録カード1枚。
- **文書作成指針の前置注入（§5・2026-07-05）**：doc_type は router で確定済み＝どの指針が要るかも確定済みなので、指針の提示を作成/レビューAI の自発的な `read_policy` 呼び出し（soft な「必ず沿う」）に委ねず、**author/reviewer の InstructionProvider（`agents/instructions.py`）が prompt 冒頭へ決定的に前置注入する**。`policy_store.render_for_doc`（共通＋当該書類の勘所だけ・履歴なし）で作る書類の scope に絞る（author は factory で scope 固定／reviewer は共用のため state["doc_type"]→scope 解決）。前月/期間の集積も同じ provider が state の digest を `format_digest_for_prompt` で prompt へ前置し、**`DigestPrepAgent` は content 無しの state-only イベント**で digest を state に載せるだけにした（下記）。`read_policy` ツールと author/reviewer への配線は撤去（improver の `read_policy_cards` は編集前提で不変）。呼び忘れの構造的排除・他書類節/履歴のノイズ削減・指針を agent の**与件**にする（前提理解→情報収集→作成の流れ）・§5 との一貫性向上。ストア未整備/障害は指針省略へ降格して生成を止めない。provider 単体＋E2E（先頭 content イベント＝author の固定）を決定論検証。
- **prep の state-only 化＝eval 互換（§12・2026-07-05）**：ADK eval の rubric judge は invocation の**先頭 content イベント**の著者の developer instructions を引き、LLM 段のみを登録するため、非LLM の prep（`DigestPrepAgent`）が content 付きイベントを先頭に置くと採点不能になる（`policy_prep`/`period_prep not found`）。これが原因で**保育経過記録 evalset 6件は追加時（2026-07-04）から採点できていなかった**（baseline は日誌16件で採点済み・child_record 追加後は未採点）。指針を InstructionProvider へ、集積を **content 無しの state-only イベント**へ移し、先頭 content 段＝author に保つことで日誌16＋保育経過記録6の全 22 ケースが採点可能になった（`state["*_digest"]` は UI/scripts/tests 用に維持）。
- **育つ指針の Cloud SQL 統合（Phase 2・2026-07-05。GCS 永続化を置き換え）**：`DATABASE_URL` 設定時、`policy_store` の IO が書類アーカイブと同じ DB の `policy_books` 1行（book 丸ごと JSONB・migration 0003）を読み書きし **Cloud Run のコンテナFS 揮発を解消しつつストアを DB に一本化**。read-modify-write は `load_book_meta` の version → `save_book(if_version=…)` の compare-and-swap で楽観ロック（競合は `commit_policy_card` が rejected へ変換＝黙って上書きしない・意味論は GCS generation 時代と同一）。行不在はローカルシード（git 同梱）を返し初回書込みでシードごと DB へ乗る。`store_status` は DB 設定時 "persistent"／到達不能 "unavailable" を正直に返す。未設定はローカル降格。接続基盤は `harness/db.py`（record_store と共有）。sqlite で creds 不要にテスト済み（`POLICY_STORE_URI`/GCS バックエンドは撤去）。
- **決定論E2E（結合テスト）**：`tests/test_e2e/`。`FakeLlm` 注入で日誌/月案/保育経過記録パイプラインを実 ADK ランタイムに
  end-to-end で通し、連結・APPROVED 早期終了・**NEEDS_REVISION での再作成（2枚目が確定）**・巡回上限・確定3経路・
  HITL 不発火・**真の承認ゲートの書き戻し**・**L2/L3 還流・ルータ分岐（日誌/月案/保育経過記録）**を creds 不要・決定的に検証（品質採点は層B eval＝別系統）。起動は `/e2e` skill。
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
- **eval ケース**：`eval/cases/child_record.evalset.json` 6 件 ＋ `eval/cases/nursery_record.evalset.json` 3 件（§19・L4・session_input で doc_type/保育経過記録を seed・小学校引継ぎ＝開示前提の参照ドラフト）＝計 9 件（実在しない仮名ロスターのみ・現場の多様な状況。旧 日誌16件は手入力化で撤去済み＝件数下限は tests/test_eval_cases.py の ≥8）。rubric（3軸）は doc_type 非依存で全ケースを採点する。
  子どもは現場の日誌に寄せた仮名（下の名前＋ちゃん/くん）＋月齢・数量化した生活記録・具体的な姿で、`tests/test_eval_cases.py`
  の `_FICTIONAL_ROSTER` allowlist が実名/未知名の混入を機械的に落とす（§14）。
  件数≥8・参照ドラフトが型を通る・実名なしを `tests/test_eval_cases.py` で決定論検査。
- **配信（層A）**：`Dockerfile`＋`.dockerignore`（`uvicorn server:app`・scale-to-zero。指針ファイル＋`eval/baseline.json` のみ同梱）、
  `.github/workflows/deploy.yml`（WIF で `gcloud run deploy --source .`。**`CLOUDSQL_INSTANCE` 設定時は deploy の前に
  Cloud SQL Auth Proxy 経由で `alembic upgrade head` を自動適用**＝コードとスキーマを同じ deploy で前進させ migration drift を
  構造的に防ぐ・additive/expand 前提・失敗時は deploy 中止・前提は `DEPLOY_SA` へ `roles/cloudsql.client`＋DB URL secret への
  `roles/secretmanager.secretAccessor`）、`.github/workflows/eval-gate.yml`
  （nightly/手動・WIF で creds 採点）。決定論 CI（`ci.yml`）は従来どおり毎PR・creds 不要。
  docker build → コンテナ起動で `/docs` 200 を実機確認済み。
- **本番運用ハードニング（2026-07-05・Google Cloud ベストプラクティス突合せ）**：Cloud Run 配信のセキュリティ/コスト MUST を
  コード側で配線（GCP 側の一度きり設定は `docs/ライブ実行手順.md`「本番運用ハードニング」）。
  ①`Dockerfile`＝**非 root（uid 10001 appuser）**・**exec 形式で uvicorn を PID1** 化（scale-down SIGTERM を直接受け in-flight の
  SSE/LLM をグレースフルに閉じる）・uv を `ARG UV_VERSION` 固定＋ベース `slim-bookworm` 固定（digest 固定は TODO）。
  ②`deploy.yml`＝`--max-instances`（`MAX_INSTANCES` var・既定4＝公開＋LLM 課金の実質ストッパ）・`--service-account`
  （`RUNTIME_SA` var＝最小権限。未設定は既定 Compute SA へ降格＋`::warning::`）・`DATABASE_URL` の注入を **Secret Manager 優先**
  （`DATABASE_URL_SECRET` var→`--set-secrets`／無ければ GH secret 平文 env にフォールバック＋警告）・`--labels`・
  **認証ポリシーの再現**（`--no-iap --allow-unauthenticated` で案内画面を公開し、`GOOGLE_OAUTH_CLIENT_ID` var＋
  `SESSION_SECRET` secret を必須注入してアプリ内 Google session が保護）・**env 保全**（`--set-env-vars` は全置換ゆえ `MODEL_LOCATION`＝
  var 既定 global を明示管理し、再デプロイで生成 location が落ちないようにする）。
  ③可観測性＝`src/hoiku_agent/logging_config.py`（**stdout 1行 JSON・severity・`X-Cloud-Trace-Context` 相関**を Cloud Run の
  ロギングエージェント昇格に委ねる＝Cloud Logging クライアントは手組みしない）。`server.py` 入口で `configure_logging()`＋
  `install_trace_middleware()`。ローカルは `K_SERVICE` 無しでテキスト降格（`LOG_FORMAT`/`LOG_LEVEL`）。決定論テスト
  `tests/test_logging_config.py`。docker build→起動で 非root/PID1/HTTP200/JSON ログ/SIGTERM exit0 を実機確認。
  **スパン＝Cloud Trace エクスポート（層A 構想の「初日から」の残り半分・2026-07-09）**：ADK ネイティブの
  `trace_to_cloud` を `server.py` が `settings.trace_to_cloud`（env `TRACE_TO_CLOUD`・既定 false）で中継し、
  agent 実行・LLM・ツール呼び出しの OTel スパンを Cloud Trace へ送る（1リクエストの軌跡を Trace エクスプローラで
  追える＝ログ相関と対の両輪。自前 OTel は手組みしない）。`deploy.yml` が本番へ `TRACE_TO_CLOUD=true`（var で
  false 可）を注入し、実行SAに `roles/cloudtrace.agent`（書込専用）を付与する（ライブ実行手順 §1）。exporter は
  `opentelemetry-exporter-gcp-trace` を直接依存に明示（ADK は import するだけで同梱しない＝uvicorn と同じ流儀）。
  未設定/未付与でも落ちない（送らない/export エラーログのみ＝降格safe）。
  残（GCP 運用）：請求予算アラート・WIF の自リポ限定 attribute condition・（将来）IAM DB 認証・脆弱性スキャン。
- **保育士向け配布 UI（`web/`・B-full）**：`server.py` が `register_web_ui(app)` で `get_fast_api_app` に同居させる。
  保育士 SPA＝`/app/`（`/` も着地）、dev UI＝`/dev-ui/`、自前 API＝`/api/*`。SPA は**上位4タブ（書類を作る／育てる／クラス・園児／書類を見る）**＝**書類を作る**（日誌/月案/保育経過記録/保育要録を
  カテゴリ別グループ表示の種別メニュー（`app.js` の `DOC_CATEGORIES`＋`renderDocMenu`＝4カテゴリ〔指導計画/保育記録/保護者連携/園運営〕）で1タブに統合＝
  フロー本体は共通で入力欄と seed だけ切替・対象児コンボは共有・結果エリアは種別ごとに保持・生成中は種別切替をロック＝対応済み（DOC_TYPES）は
  `DocTypeRouter` の doc_type 分岐と 1:1／**今後対応予定〔年間指導計画/週案/日案/連絡帳/おたより/勤務シフト〕は灰色の非選択 placeholder＝ロードマップ提示・生成しない**）／**育てる**（＝2サブタブ 指針を育てる｜表記ルール＝
  `setupSubTabs`。仕組みは分離のまま（policy_store／notation_store・§5）で保育士の「教える場所」を1タブに集約＝presentation の統合。「指針を育てる」は
  対象書類セレクタ（`POLICY_TARGETS`＝PolicyScope と 1:1）でカードデッキを「共通＋その書類」に絞り込み〔`policy.setFilter`＝`render_for_doc` の範囲と一致〕、
  `/api/improve` に `target_scope` を送って提案 scope の既定にする＝反映先の可視化・改善AIは既定として尊重しつつ内容的に共通なら ask で提案）／**書類を見る**（アーカイブ閲覧＝
  `record_store` の確定書類を**ファイルシステム風ツリー（種別→子ども→書類）**で辿る＝`records.js`・`GET /api/records`（メタ一覧を1回・本文なし）で階層をクライアント構築→
  ファイルを開いたときだけ `GET /api/records/{id}`＝`record_store.get_document` で現行版の整形テキスト＋entry を取り（セッション内キャッシュ）、右ペインに整形テキスト＋帳票PDF を描く。
  **表示に必要な分だけ読む**＝折りたたみ既定で展開したフォルダの DOM のみ都度生成・重い本文はファイルを開いた分だけ取得。読取なので非ゲート・未接続/不在は正直に降格。前月・期間の集計など参照データの点検にも使える）。日誌/月案/保育経過記録/保育要録はフロントが ADK ネイティブ REST
  （`/run_sse`・session 作成で月案/保育経過記録/要録の seed・`PATCH` 承認・`function_response` で HITL 再開）を直接駆動（自前 Runner なし＝§9。クラス月案は seed 3系統＝`GET /api/records/class-monthly-seed`・保育経過記録は期間日誌＋前回までの記録〔`exclude_period`〕・要録は年度指定＋それまでの保育経過記録すべて＝`GET /api/records/child-record-entries`）。
  **確定下書きは標準様式の見た目の編集フォーム（`docedit.js`）で保育士が欄ごとに自由に編集**でき（出欠/個別記録/教育ねらいは
  追加削除可・タグは年齢に応じ `/api/form-meta` の Enum 語彙から多選択・記録日/対象月は read-only）、保存時に
  `/api/finalize-edit`（harness の `finalize_entry` 中継）で再 validate/整形→state へ反映、承認で公式記録にロック（型成立ゲートは編集後も有効）。
  **現場でそのまま綴じる最終形＝園の帳票PDF**：確定/編集後の `final_entry` を「帳票PDFをダウンロード」で保存できる（`/api/export-pdf`→
  `chohyo_pdf.render_pdf`＝ReportLab で A4 罫線帳票・日誌/月案/保育経過記録/保育要録・欄順は標準様式に一致・**描画のみで型検査は harness**）。**末尾に確認印欄
  （担任/主任/園長）を置き公式記録の体裁を満たす**。生活記録（食事/睡眠/排泄/機嫌・体調）の4列表は本文全幅で他行と罫線をそろえる
  （ReportLab の Table 既定 hAlign=CENTER によるズレを LEFT＋全幅で是正）。ヘッダは気温・組（`DiaryEntry` の任意欄）を記入時のみ添える。日本語は
  IPAex ゴシックを埋め込むため閲覧側の CJK フォントに依存せず化けない（Heisei CID 非埋め込みの空白化を回避）。生成は純 pip・
  システムライブラリ不要でフォントは同梱＝**Dockerfile 不変**。LLM 非課金なので非ゲート。§18「園の様式で出す一段」に対応（標準様式まで到達・特定園の欄差は現場依存で残課題）。
  **改善エージェント（指針を育てる）**は `improver_stream.py` が `build_improver_agent` を InMemoryRunner で SSE 駆動（別エントリ維持）し、
  `policy.js`（温かい1タブ）が「指針カード閲覧＋変更履歴／提案→意味的競合の比較相談→保育士決定で即反映」をライブに描く（`/api/policy`＝カード＋履歴＋store）。
  LLM を回す口（作成・改善・取込・校正）は `llm_budget` が Google Sign-In の subject ごとに1時間1000円、
  全利用者で1日10000円の予約枠を原子的に確保してから実行する。クラス月案の実測（入力15,109・出力2,237 token、約6.85円）を基準に、
  レビュー最大3巡と余裕を見て1実行35円を予約する。UI は残額を表示し、上限時は 429 と再開時刻の案内を出す。
  **実機検証済み（creds 有・gemini-2.5-pro＋Memory Bank）**：日誌 HITL 発火→`function_response` 再開→確定、月案 L2 還流、編集フォーム保存→再 validate。
  **指針を育てる（即反映）の live creds スモークは未実施**（非LLM面は検証済み）。非LLM面（配線・静的配信・コストゲート・`/api/policy` 形・
  `/` 着地・`form-meta`/`finalize-edit`）は `tests/test_web.py` で決定論検証。`web/CLAUDE.md` に規約。
- **Google Sign-In（Phase 3・2026-07-11）**：`/` は案内画面を返し、Google Identity Services の**公式ボタン**を押したときだけ
  Google の選択・同意画面へ redirect する。`web/auth.py` が callback の ID token を Google の公開鍵で署名・audience・期限まで検証し、
  `email_verified` と double-submit CSRF を確認して署名付き session を作る。Cloud Run IAP は URL 到達前に強制転送するため
  `deploy.yml` で `--no-iap --allow-unauthenticated` とし、代わりに `/app/`・`/api/*`・ADK 実行口を session 無しで fail-closed にする。
  `record_store.users.google_subject`（migration 0010）が Google の不変 `sub` を正とし、email 変更を同一ユーザーとして追随する。
  `touch_user`／`set_user_display_name`／actor 解決は検証済み session ＞ 自己申告。`SESSION_SECRET`（GitHub Secret）と
  `GOOGLE_OAUTH_CLIENT_ID`（GitHub Variable）が無い本番 deploy は失敗させる。決定論テストは `tests/test_web.py` の案内画面・
  session 保護・CSRF・auto-provision と `tests/test_harness/test_record_store.py` の subject 永続化で担保する。
- **書類アーカイブ（Phase 1・本番運用ブラッシュアップ 2026-07）**：`harness/record_store`（Cloud SQL PostgreSQL・
  children/documents/document_versions/audit_events・Alembic）＋web 配線（`/api/records`・`/api/records/approve`・
  `/api/records/diary-entries`・`/api/children`・担当者名入力＝audit の actor 自己申告）。**確定/編集/承認が
  版管理つきで永続化**され（AI 確定と保育士編集を区別＝修正差分の一次データ）、**L2/L3 の seed（前月・期間の
  日誌）はアーカイブから自動取得**（web・scripts とも。未接続/該当なしはサンプルへ降格＝eval/CI は DB 非依存で不変）。
  `deploy.yml` は `CLOUDSQL_INSTANCE`（var）＋ DB 接続注入（**Secret Manager `DATABASE_URL_SECRET`＝推奨**／
  旧 GH secret `DATABASE_URL` 平文はフォールバック・警告）で任意配線。テストは sqlite で決定論
  （`tests/test_harness/test_record_store.py`・`tests/test_web.py`）。
- **書類アップロード取込（「書類を見る」タブ・2026-07-06）**：既存の保育書類（**PDF/Word(.docx)/Excel(.xlsx)**）を
  取り込み、LLM で既存スキーマ（DiaryEntry／**ClassMonthlyPlan〔クラス月案・§18・区分×領域グリッド＝主対象児なし〕**／
  ChildRecord／NurseryRecord。個別月案 MonthlyPlan も backend `_KINDS` は受理〔旧経路〕だが UI 取込口はクラス月案に一本化）へ
  書き起こして、**アプリ生成物と同じように次の書類作成で参照できる**ようにする（唯一の新規能力＝ファイル→entry の抽出。以降は既存資産を再利用）。
  3責務の線に沿って配線：**format 変換（決定的・web）**＝`web/upload_extract`（docx: python-docx／xlsx: openpyxl／
  pdf: Gemini マルチモーダルへ生 bytes）→ **書き起こし（agentic・agents）**＝`agents/upload_parser_agent`
  （`build_upload_parser_agent`＝単一 LlmAgent・**別エントリ**＝root_agent に載せない・種別別 instruction・与件を前置・
  ```json フェンス出力）を `web/upload_parse` が InMemoryRunner で1パス駆動（improver_stream と同型）→ **検査・整形
  （決定的・harness）**＝対象キー/child/age_band を保育士入力で**権威的に上書き**してから `finalize_entry`。web の口は
  `POST /api/parse-upload`（multipart・**LLM を回すので `llm_budget` の利用枠を予約**・未対応形式/種別 400・
  creds 無/LLM 失敗は 200＋parse_error で正直に降格）。UI は**ファイルシステム的**＝4種別フォルダ（日誌／**クラス月案**／
  保育経過記録／要録＝`TYPE_ORDER`。旧・個別月案は常時フォルダから外し、過去に取り込んだ分があれば末尾に閲覧のみで温存）を
  常時表示し、フォルダ（＋personal 種別の子フォルダ）を開くと先頭に「取り込む」行が出て kind〔＋child〕が場所で決まる（`records.js`）→
  取込フォーム→解析→**既存 `docedit.js` の編集フォームで確認・修正（HITL）**→`/api/finalize-edit`→`/api/records`
  （`author_kind="imported"`）で保存＝ツリーに出現し **L2/L3/L4 seed として自動参照**（`list_diary_entries`／
  `list_child_record_entries` が拾う）。生ファイルは保存しない（抽出→entry のみ＝PII blob を残さない）。
  決定論テスト＝`tests/test_web.py`（upload_extract／parse-upload の権威的上書き・降格・未対応形式・ゲート）・
  `tests/test_harness/test_record_store.py`（imported→audit import）。実 LLM ＋実ブラウザ E2E（日誌/保育経過記録の取込→保存→
  下流 seed 参照）を検証済み。
- **👍👎＋ひとことの軽量フィードバック導線（2026-07-08）**：書類作成を通して「回す」が自然に進むよう、確定/承認画面・
  アーカイブ詳細に 👍👎＋ひとことを置いた（設計は §4/§8 の入力＝「修正メモ・👍👎」を想定済みだが未配線だった導線を足す）。
  3責務の線で配線：**保存＝harness**（`record_store.Feedback`＝独立テーブル・migration 0008・document＋その版に紐付け・
  `save_feedback`/`list_feedback`・降格safe）／**指針化の判断＝improver**（既存 `/api/improve` の `feedback` を実値化＝
  別エントリ維持・毎回カードを作らせず「一般化できる勘所か」を判断させる分岐を `IMPROVER_INSTRUCTION`／両 `_build_input` に追加）／
  **中継/描画＝web**（`POST/GET /api/records/feedback`＝書込ゲート/読取素通し・actor は `_resolve_actor`・`feedback.js`＝
  送信で保存→ひとことがあれば「この気づきを指針に活かす」で**インラインに `makePolicy` を再インスタンス化**して提案→比較相談→
  即反映＝育てるタブと同じ描画を再利用〔二重実装しない〕・doc kind→scope は `scopes.js` の `POLICY_SCOPE_OF` に一本化）。
  **eval とは decouple のまま**（👍👎 を eval ゲートに自動注入しない）・**Memory Bank 書き戻しとは別物**（園横断の勘所＝policy_store）。
  決定論テスト＝`tests/test_harness/test_record_store.py`（版追従・verdict検証・降格）・`tests/test_web.py`（保存/一覧・書込ゲート/
  読取素通し・Google session actor 優先・DB未接続 skipped）。実 LLM ＋実ブラウザ E2E（👎＋ひとこと→保存〔version_seq/actor 紐付け〕→
  活かす→提案〔scope=保育日誌〕→保育士決定→即反映→カード persistent＋履歴〔回した証拠〕）を検証済み。

残課題（**外部リソース・実データ・各自 GCP 設定に依存。コードは降格付きで配線済み**＝コードだけでは閉じられない）:
- **各自 GCP のプロビジョニング＋ env 設定**（コード・スクリプトは実機検証済み）:
  - Vertex RAG corpus：`uv run python scripts/provision_rag_corpus.py --create`（新規 GCP は RagManagedDb を
    serverless へ REST 切替＋Vector Search API・埋め込みは `text-multilingual-embedding-002`）→ `.env` の `RAG_CORPUS`。
    未設定は `search_guideline` 降格。
  - Memory Bank：`uv run python scripts/provision_memory_bank.py --create`（生成モデル＋日本語/子の姿カスタマイズ）
    → `.env` の `AGENT_ENGINE_ID`。未設定は InMemory 降格。
  - 育つ指針は書類アーカイブと同じ Cloud SQL（`DATABASE_URL`）に統合済み＝追加のプロビジョニング不要
    （migration 0003 の適用のみ。未設定はローカル降格＝Cloud Run では揮発・store_status が "ephemeral" を正直表示）。
  - 書類アーカイブの Cloud SQL：`gcloud sql instances create`（PostgreSQL 16・db-f1-micro）→ Auth Proxy 経由で
    `uv run alembic upgrade head` → `.env`／Cloud Run の `DATABASE_URL`（＋`--add-cloudsql-instances`＝
    `deploy.yml` の `CLOUDSQL_INSTANCE`/`DATABASE_URL`）。未設定は降格（永続化なし・seed はサンプル）。
  - 手順は `docs/ライブ実行手順.md`。Gemini/Vertex 自体は接続済み（ADC＋`GOOGLE_CLOUD_PROJECT`/`GEMINI_MODEL`）。
    既定モデル `gemini-3.5-flash` は Vertex **global 専用**のため、生成だけ `MODEL_LOCATION`（既定 global）へ固定し、
    RAG/Memory は `GOOGLE_CLOUD_LOCATION`（regional）のまま分離する（`src/hoiku_agent/models.py`＝`build_model`）。
- **層A の実デプロイ／eval ゲートCI の有効化**：`deploy.yml` / `eval-gate.yml` は用意済みだが、GCP 側の
  **WIF（鍵レス）設定＋リポジトリ変数**（`WIF_PROVIDER`/`DEPLOY_SA`/`GCP_PROJECT_ID` 等・ハードニングは
  `RUNTIME_SA`/`DATABASE_URL_SECRET`/`MAX_INSTANCES`＝`docs/ライブ実行手順.md`「本番運用ハードニング」）が前提（未設定なら job は skip・降格）。
  **DB 自動 migration を効かせるなら `CLOUDSQL_INSTANCE` 設定＋`DEPLOY_SA` に `roles/cloudsql.client`＋DB URL secret への
  `roles/secretmanager.secretAccessor` を付与**（deploy 前に `alembic upgrade head` を自動適用＝手動忘れによる drift の再発防止・§ prod-db-migration-drift）。
  eval ゲートCI は採点に creds が要るため `google-adk[eval]`（`--extra eval`）＋ WIF が前提。
  （**main 比 baseline の保存・比較は実装済み**＝committed `eval/baseline.json`。WIF を有効化すれば nightly が
  初回採点して baseline を埋め、以後 PR が非劣化比較する。未採点（mean=null）の間は must_fix 0＋採点可能を緑とする。）
- **特定園の実様式1枚による微調整**（§18）：`write_draft`/`write_monthly_draft` は**ネット調査で裏取りした 0–2 個別の
  標準様式**（章立て・順序・養護2本柱・生活記録・制度用語）に準拠済み。残るのは特定園の欄差（午睡ブレスチェック間隔欄の
  型化要否・家庭連携/食育/健康の分割粒度・0歳=3つの視点 vs 旧式 0歳5領域など）をヒアリングで確定する微調整のみ＝
  **現場依存で、コードだけでは閉じられない**（標準様式準拠まではコードで到達済み）。
- **現場の修正差分による eval ケースの質的拡充**（§12）：v0 は実在しない仮名ロスター 9 件（保育経過記録6＋保育要録3・日誌16は手入力化で撤去）。現場の👍👎・修正差分で「リアルな失敗」を
  足すのは現場との運用依存（PII 非コミットを守りつつ＝§14）。
- **rubric 文面の echo 安定化**（§12）：ADK は judge の echo テキストで rubric を照合するため、長い軸 rubric
  （axis_guideline_alignment）は judge の言い換えで照合漏れし一部ケースでその軸が欠落する（mustfix は不影響・
  軸平均は present のみ）。rubric 文面を短く echo 安定にする調整（要 live 再採点で確認）。
- **二階の堅牢化はスコープ外**（§8/§15）：大規模ルールの自動競合検出・多保育士調停はやらない（「閉じる1事例」で足りる）。
- ADK 2.3.0 で LoopAgent/SequentialAgent は deprecated（将来 Workflow へ）。設計（§6/§7）が前提とする API で
  2.3.0 の Workflow 代替は非公開のため v0 はこのまま使う（中期 TODO で移行）。
