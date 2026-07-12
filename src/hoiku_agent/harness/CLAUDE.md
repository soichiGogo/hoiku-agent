# harness/ ＝ 決定的「型の保証」層（責務①）

ここで Claude がすること：**文書というモノの成立**（必須欄・年齢分岐・順序・集積・指針カードストア）を
**決定的なコード**で保証する。設計コンテキスト §4「一階＝作成本体」/ §5「責務境界」。

## 越えてはいけない一線

- **LLM を呼ばない。** `LlmAgent`・プロンプト・「何を書くか」の判断をここに書かない。それは
  `../agents/` の責務。ここは純粋関数とワークフロー制御（順序・ループ・分岐）だけ。
- **決定的ロジックの実体はこの層に1つだけ。** `../tools/validate_fields.py` と
  `../tools/write_draft.py` は本層を呼ぶ**薄いラッパ**であり、ロジックを再実装しない（§5/§6）。
  ツール側にロジックが滲み出ていたらレビューで差し戻す。
- ここに書ける＝**`tests/test_harness/` から LLM 非依存・高速にテストできる**。テストが書けない
  なら agents/ の責務が混入している疑い。

## ファイルの責務

- `schema_check.py` … `validate_fields`（日誌）/ `validate_monthly_fields`（個別月案）/
  `validate_class_monthly_fields`（クラス月案・§18）/ `validate_child_record_fields`（保育経過記録・§19）/
  `validate_nursery_record_fields`（保育要録・§19・L4）：必須欄＋年齢分岐（0–2＝3つの視点 /
  3–5＝5領域）。分岐の実体は `_required_tag_type` に1つ（日誌・月案・保育経過記録・要録で共用。要録は年長＝5領域固定）。
  日誌の生活記録必須は **0–2 のみ**（3–5 は任意＝全年齢対応・§19）。**クラス月案は例外**＝様式が全年齢で5領域
  グリッドのため3つの視点分岐を課さず、グリッド各行のねらい＋0–2 の個人目標（≥1）を検査する（§18）。
- `draft.py` … `write_draft`（日誌）/ `write_monthly_draft`（個別月案）/ `write_class_monthly_draft`（クラス月案・§18）/
  `write_child_record_draft`（保育経過記録・§19）/ `write_nursery_record_draft`（保育要録・§19・L4）：pydantic →
  **標準様式テキスト**へ整形。**本文レイアウト（章立て＝セクションの順序・見出しラベル・種別・出し分け）は
  `template_store` の様式テンプレート（データ）を歩いて描く**（§18＝園差をコード改修でなくテンプレ編集で吸収）。
  ヘッダ合成と個別記録ブロック・生活記録・出欠サマリ等の**構造描画はコード**に残す（テンプレは式言語を作らない）。
  順序＝日誌:養護2本柱/生活記録/養護→教育、保育経過記録:発達の経過→配慮特記→家庭連携→総合所見→次期、要録:最終年度の
  重点→個人の重点→保育の展開→特に配慮すべき事項→最終年度に至るまでの育ち（この順序・ラベルはテンプレが持つ）。
  **クラス月案は非線形の構造様式**（保育経過記録マトリクスと同様 template_store は通さず、レイアウトのデータ＝
  `schemas/class_monthly.GRID_ROWS` を歩いて描く＝§18）。確定出力は pipeline 末尾で実行。
- `template_store.py` … **様式テンプレート＝本文レイアウトの宣言的データ**（`schemas/template.py` の
  DocTemplate/Section・閉じた種別語彙）のストア。`load_template(doc_type)` を**3レンダラ共通で読む**＝テキスト整形
  （draft.py）・帳票PDF（web/chohyo_pdf の線形様式）・編集フォーム（web/docedit.js・`/api/doc-template`＝`book_view`）が
  本文セクションの順序/ラベルをここから取る（レイアウトの三重管理を解消・§18）。レイアウトのデータのみ（validation は
  持たない＝型の保証は schema_check・§5）。置き場は policy_store/notation_store と同型＝明示 path ＞ `DATABASE_URL`
  （`template_books` 1行 JSONB・version 楽観ロック・行不在はローカルシード。**DB 到達不能／テーブル未整備＝migration 0005
  未適用等の DB 障害も同梱シードへ降格**＝テンプレは全書類の write_*／帳票PDF／編集フォームが確定処理で必ず読むため
  fail-loud だと全生成が落ちる。レイアウトは常にシードで代替可＝§5「降格safe」。`store_status` は DB を直接叩いて到達性を
  正直表示）＞ ローカル `knowledge/様式テンプレート.json`
  （git はシード・migration 0005）。編集 UI は現状スコープ外（園差の実需で後続）。保育経過記録の帳票PDF は年間マトリクス様式
  （線形でない）ため対象外。
- `notation_store.py` … **ひらがな表記DX＝表記ルール辞書＋決定的な正規化器**（「子供→子ども」等の置換・混入
  スペース除去）。CRUD（保育士が育てる編集辞書）＋正規化（`normalize_text`/`normalize_entry_dict`＝**叙述系
  フィールド限定**で仮名/タグ/日付は不変＝誤変換を型で防ぐ）＋IO（`notation_books` 1行 JSONB・version 楽観ロック・
  ローカル `knowledge/表記ルール.json` シード・降格）。policy_store と同じ哲学（決定的実体はここに1つ・置き場は IO 節で
  解決・clock 外部注入）。**育つ指針カード（agentic な勘所）とは別の道具＝決定的な表記の統一**（線を混ぜない）。
- `finalize.py` … `finalize_document`（日誌）/ `finalize_monthly_document`（個別月案）/
  `finalize_class_monthly_document`（クラス月案・§18）/ `finalize_child_record_document`（保育経過記録）/
  `finalize_nursery_record_document`（保育要録）：復元→**表記正規化**→検査→整形（正規化は `notation_store` を呼び
  validate/write の前に決定的に当てる＝以降は整えた本文に走る・降格safe。変更点は `FinalizedDocument.notation_changes`）。
  汎用本体 `_finalize` を parse/validate/write 差し替えで共用（二重実装しない）。`finalize_entry(dict)` は
  編集UI用＝編集後 entry を直接 正規化→validate/write 再実行（web から中継・実体はここに1つ）。
- `aggregate.py` … `aggregate_by_child`（Counter 版）/ `prev_month_digest`（state 用 serializable）/
  `format_digest_for_prompt`（集積の人間可読テキスト・label 切替）/ `child_record_digest` ＋
  `format_record_digest_for_prompt`（保育経過記録集積＝**要録 L4〔それまでの全期〕・保育経過記録の「前回まで」・
  クラス月案の「クラス児童のこれまで」で共用**・child_id 別・期順）/ `class_plan_history_digest` ＋
  `format_class_plan_history_for_prompt`（クラス月案の自己履歴＝月順の目標・ねらい・記入済み月末評価＝依存モデル
  2026-07）。要約生成は各 author に委ねる（§10/§19）。
- `pipeline.py` … 作成パイプラインの**共用機構**（月案/クラス月案/保育経過記録/保育要録が使う）：authoring_loop
  （作成→レビュー→ApprovalGate の巡回）→ 確定/HITL の順序制御。**保育日誌の AI 生成パイプライン（旧
  `build_document_pipeline`）は退役**（日誌は手入力＝web の docedit→`finalize_entry`・ヒアリング 2026-07）。
  `build_authoring_loop` が author を巡回に包み NEEDS_REVISION で
  再作成、APPROVED 早期終了の**判定**（ApprovalGate）はここ（制御＝決定的）、レビュー内容の**生成**は reviewer。
  `FinalizeAgent(kind=...)` で月案/クラス月案/保育経過記録/保育要録の確定を切替（実体は finalize.py）。
  pipeline は `[authoring_loop → finalize]` のみ。候補は state に seed し、author/reviewer が fetch_reference を
  呼ぶと `reference.py` が既存 aggregate を使って決定的に集計し、reference_manifest を残す（§5/§12）。
- `monthly.py` … 月案 authoring_loop→finalize。前月日誌は fetch_reference(prev_month_diaries) で取得（§10）。
- `class_monthly.py` … クラス月案 authoring_loop→finalize。3系統の候補＋在籍児名簿（class_roster）と児童別未反映境界は reference.py が担当。
  個別月案（1児）と別 doc_type＝**文書の年齢帯単位**で、区分×領域グリッド（養護2本柱＋教育5領域）は
  0–2/3–5 共通＝3つの視点分岐を課さない（様式忠実）。grid の正準7行そろえは
  `schemas/class_monthly.ClassMonthlyPlan` の model_validator（レイアウトのデータは GRID_ROWS に1つ）。
- `child_record.py` … 保育経過記録 authoring_loop→finalize。期間日誌と前回記録は fetch_reference で取得（§19）。
- `youroku.py` … 保育要録 authoring_loop→finalize。それまでの保育経過記録を fetch_reference で取得し、日誌は足さない（§19・L4）。
- `router.py` … `DocTypeRouter` / `build_root_agent`：state["doc_type"] で月案／クラス月案／保育経過記録／保育要録を
  振り分ける決定的分岐（root_agent の実体・**既定＝クラス月案**＝§18）。**保育日誌は AI 生成を退役**したためルータに載らない
  （日誌は手入力＝web）。
- `policy_store.py` … 育つ指針＝構造化カードストアの決定的 CRUD・完全重複ガード・履歴・テキスト再生
  （全再生＝`render_to_text`（UI `/api/policy`・eval）／前置注入用＝`render_for_doc`（共通＋当該 scope のみ・
  履歴なし＝`../agents/instructions.py` の InstructionProvider が呼ぶ））・view（`/api/policy` 用）。**指針編集の決定的実体はここに1つ**
  （improver/tools はこれを呼ぶ薄いラッパ）。意味的競合の判定は LLM（improver）の責務でここは持たない
  （安全網＝完全重複のみ）。clock を持たず日時は外部注入（§8/§9）。置き場は IO 節に隔離＝
  **明示 path ＞ `DATABASE_URL`（Cloud SQL＝書類アーカイブと同じ DB・`policy_books` 1行に book 丸ごと JSONB・
  `load_book_meta`→`save_book(if_version=…)` の compare-and-swap で楽観ロック・行不在はローカルシードを
  返し version 0＝create-only） ＞ ローカル `knowledge/文書作成指針.json`（git はシード）**。純関数は置き場を知らない。
  カードを行へ射影しない（「本文 JSON が SSOT」＝record_store と同じ哲学）。
  「回した証拠」＝カード内蔵の変更履歴（decided_by 含む）。
- `db.py` … harness 共通の DB 接続基盤（engine キャッシュ・Declarative Base・JSONB variant）。
  record_store と policy_store が同じ `DATABASE_URL` を共有するための最小インフラ＝ドメインロジックを置かない。
- `demo_seed_data.py`／`demo_seed.py` … **デモ用デフォルト seed**（実在しない仮名のみ・§14）：物語時刻＝
  **FY2026 の7月中旬**。データ部（名簿 ROSTER 10人〔あおぞら5＋ひよこ5〕・CLASSES＝ひよこ組/あおぞら組・
  卒園児 GRADUATE・確定書類チェーン 計167件＝**保育日誌 138〔2026-04-01〜07-10 の平日毎日×2クラスを週テーマ×
  子ども別観察プールの決定的ローテで合成・age_months は生年月日から `age_months_on` で機械計算〕**／クラス月案8
  〔2026-04〜07・4〜6月は月末評価記入済み〕／保育経過記録20〔**年度4期・各3か月固定／前年度 FY2025**＝「前回まで」還流と年度跨ぎ集積の素〕／
  要録1〔卒園児 FY2025・小学校引継ぎデモ〕。今年度第1期の経過記録はあえて未作成＝「溜まった日誌から作る」デモの
  主戦場を残す。承認フロー体感用の UNAPPROVED＋`INCOMPLETE_DATES`〔直近2日の日誌は評価未記入＝記入導線デモ〕）と
  ロジック部（`validate_all`＝型成立検査〔is_incomplete は除外〕／`seed_workspace`＝finalize_entry→
  save_document/approve_document の冪等投入・種別×児×期間で既存スキップ・is_incomplete は検証エラーを許容し保存
  〔承認はしない＝finalized 止まり〕／`reset_workspace`＝`record_store.purge_workspace_data`→再 seed）。
  **初回ログイン（web/workspace.py の provision_user）と「データを初期化」（web `/api/account/reset`）と
  CLI（scripts/seed_children.py・seed_documents.py＝薄いラッパ）が同じ実体を呼ぶ**（二重実装しない・§5）。
  LLM 非依存・clock 外部注入・未接続は skipped 降格。整合（月齢⇄生年月日・全員毎月登場・平日のみ・閉集合）は
  `tests/test_harness/test_demo_seed.py` が検算する。
- `child_record_period.py` … 保育経過記録の対象期間を年度4期・各3か月（4〜6月／7〜9月／10〜12月／1〜3月）に
  固定する決定的実体。期の生成・現在期・構文解析・違反文言・Web選択肢を1か所で持ち、schema_check／finalize／
  record_store／帳票PDF／`/api/config` が共用する。フロントで終了月を再計算しない。
- `record_store.py` … 書類アーカイブ＝確定書類・児童マスタ・監査証跡の決定的ストア（Cloud SQL
  PostgreSQL・Phase 1）。本文は JSON（PG は JSONB）が SSOT・検索キーだけ列昇格・版管理
  （AI 確定/保育士編集を区別）・承認証跡（actor は自己申告注入）。読取は L2/L3 seed（`list_diary_entries`）に
  加え `list_child_record_entries`（指定児の保育経過記録の最新版・**全期・`exclude_period` で作成対象の期を除外**＝
  要録 L4／保育経過記録「前回まで」seed・年間マトリクス帳票の過去期埋め込み用。列割当・年度の同定は描画側
  web/chohyo_pdf の責務＝ここは引くだけ）／**クラス月案 seed（3系統＋在籍児名簿・依存モデル 2026-07）**＝`covered_until`
  （経過記録の期間終了日の最大＝未反映境界・純関数）・`list_class_child_record_entries`（名簿優先・降格は
  age_band フィルタ）・`list_class_monthly_entries`（過去クラス月案・月順）・`class_roster`（在籍児名簿＝0–2 個人目標の対象の与件・分類は `_roster_children` を seed と共用）・`class_monthly_seed_inputs`（3系統＋名簿の
  決定的合成＝scripts/web 共用）。クラス単位書類（diary/class_monthly）の dedupe_key は**年齢帯を含む**
  （同日・別クラスの版混線防止）／`get_document`（単一書類の現行版全文＝本文 entry・
  整形テキスト・確定/編集の区別＝「書類を見る」タブの閲覧・不在/不正 id/未接続は None）。**LLM もパイプラインも呼ばない**
  （永続化はフロント→web API→ここの明示フロー）。`DATABASE_URL` 未設定は降格（書込 skipped・読取 空）。
  表示名→children.id（UUID）の解決はここに1つ。**クラス（組）マスタ＝`Class`＋`children.class_id`**（migration 0007）＝
  園の名簿管理（`list_classes`/`upsert_class`/`assign_child_to_class`/`list_children_in_class`）で保育士がクラスを定義し
  児童を割り当てる＝**日誌手入力フォームの roster・年齢帯自動決定・園児登録の受け皿**（同一性は name+fiscal_year・現在の所属1本）。
  `users`＋`touch_user`／`set_user_display_name`（Phase 3）＝Google Sign-In の検証済み `sub` を正として
  初回アクセスで auto-provision（email は変更追随する属性・migration 0010）・`set_user_display_name` で display_name を後から設定（自分の表示名・認可は持たない）。
  **書類フィードバック＝`Feedback`（👍👎＝verdict up/down＋comment＋actor・migration 0008・`save_feedback`/`list_feedback`）**＝
  確定/承認画面から送る軽量シグナルを document＋その版（送信時点の現行版）に紐付けて残す（§8「回す」の一次入力＋§12 eval 質的拡充の原資）。
  audit_events（操作の証跡）とは関心事が別なので独立テーブル（評価の生ログ・混ぜない・降格safe）。
  スキーマ適用は repo root の Alembic（`migrations/`）。clock は外部注入。

## スタブを埋めるとき

場当たりで埋めない。`TODO(設計)` は設計コンテキスト §5/§6/§10 を読んでから既存の型に沿って実装する。
