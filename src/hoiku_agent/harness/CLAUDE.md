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

- `schema_check.py` … `validate_fields`（日誌）/ `validate_monthly_fields`（月案）/ `validate_child_record_fields`
  （保育経過記録・§19）/ `validate_nursery_record_fields`（保育要録・§19・L4）：必須欄＋年齢分岐（0–2＝3つの視点 /
  3–5＝5領域）。分岐の実体は `_required_tag_type` に1つ（日誌・月案・保育経過記録・要録で共用。要録は年長＝5領域固定）。
  日誌の生活記録必須は **0–2 のみ**（3–5 は任意＝全年齢対応・§19）。
- `draft.py` … `write_draft`（日誌）/ `write_monthly_draft`（月案）/ `write_child_record_draft`（保育経過記録・§19）/
  `write_nursery_record_draft`（保育要録・§19・L4）：pydantic → **標準様式テキスト**へ整形。**本文レイアウト
  （章立て＝セクションの順序・見出しラベル・種別・出し分け）は `template_store` の様式テンプレート（データ）を
  歩いて描く**（§18＝園差をコード改修でなくテンプレ編集で吸収）。ヘッダ合成と個別記録ブロック・生活記録・
  出欠サマリ等の**構造描画はコード**に残す（テンプレは式言語を作らない）。順序＝日誌:養護2本柱/生活記録/養護→教育、
  保育経過記録:発達の経過→配慮特記→家庭連携→総合所見→次期、要録:最終年度の重点→個人の重点→保育の展開→特に配慮すべき事項→
  最終年度に至るまでの育ち（この順序・ラベルはテンプレが持つ）。確定出力は pipeline 末尾で実行。
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
- `finalize.py` … `finalize_document`（日誌）/ `finalize_monthly_document`（月案）/
  `finalize_child_record_document`（保育経過記録）/ `finalize_nursery_record_document`（保育要録）：復元→**表記正規化**→検査→整形（正規化は `notation_store` を呼び
  validate/write の前に決定的に当てる＝以降は整えた本文に走る・降格safe。変更点は `FinalizedDocument.notation_changes`）。
  汎用本体 `_finalize` を parse/validate/write 差し替えで共用（二重実装しない）。`finalize_entry(dict)` は
  編集UI用＝編集後 entry を直接 正規化→validate/write 再実行（web から中継・実体はここに1つ）。
- `aggregate.py` … `aggregate_by_child`（Counter 版）/ `prev_month_digest`（state 用 serializable）/
  `format_digest_for_prompt`（集積の人間可読テキスト・label で月案 L2＝前月／保育経過記録 L3＝期間を切替）/
  `child_record_digest` ＋ `format_record_digest_for_prompt`（保育要録 L4＝**日誌でなく最終年度の保育経過記録**を
  child_id 別・期順に集計）。要約生成は各 author に委ねる（§10/§19）。
- `pipeline.py` … 日誌：authoring_loop（作成→レビュー→ApprovalGate の巡回）→ 確定/HITL の順序制御
  （旧 `workflow/document_pipeline.py`）。`build_authoring_loop` が author を巡回に包み NEEDS_REVISION で
  再作成、APPROVED 早期終了の**判定**（ApprovalGate）はここ（制御＝決定的）、レビュー内容の**生成**は reviewer。
  `FinalizeAgent(kind=...)` で日誌/月案/保育経過記録/保育要録の確定を切替（実体は finalize.py）。**pipeline に prep 段は置かない**
  ＝文書作成指針は author/reviewer の InstructionProvider（`../agents/instructions.py`）が `policy_store.render_for_doc`
  を prompt 冒頭へ前置注入する（探索を LLM の read_policy 呼び出しに委ねず決定的に用意＝§5）。**prep を先頭に置いて
  content イベントを出すと ADK eval の rubric judge が非LLM先頭段を採点不能にする**ため、集積の `DigestPrepAgent`
  （monthly.py）・`RecordDigestPrepAgent`（youroku.py・L4）も content 無しの state-only イベントにしてある（§12）。
- `monthly.py` … 月案：`DigestPrepAgent`（旧 MonthlyPrepAgent を入出力キーで一般化。前月日誌を child_id 別集計＝
  L2 還流の決定的部分・保育経過記録の L3 とも共用。**content 無しの state-only イベント**で `state["*_digest"]` に載せるだけ
  ＝集積の prompt 前置は author/reviewer の InstructionProvider が担う。content を持たせないのは eval judge が
  非LLM先頭段を採点不能にするのを避けるため＝§12）→ 月案 author の authoring_loop（日誌と共用）→ 確定。
  `build_monthly_pipeline`。集計＝harness／要約＝author（§10）。
- `child_record.py` … 保育経過記録（§19）：`DigestPrepAgent`（period_prep・period_entries→period_digest＝L3 還流）→
  保育経過記録 author の authoring_loop（共用）→ finalize(kind="child_record")。`build_child_record_pipeline`。
- `youroku.py` … 保育要録（§19・L4）：`RecordDigestPrepAgent`（record_prep・**最終年度の保育経過記録**（record_entries）を
  `aggregate.child_record_digest` で集計→record_digest＝日誌でなく保育経過記録を集める・content 無し state-only）→ 要録 author の
  authoring_loop（共用）→ finalize(kind="nursery_record")。`build_nursery_record_pipeline`。年長=5領域固定。
- `router.py` … `DocTypeRouter` / `build_root_agent`：state["doc_type"] で日誌／月案／保育経過記録／保育要録を振り分ける
  決定的分岐（root_agent の実体・既定＝保育日誌＝§3/§19）。
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
- `record_store.py` … 書類アーカイブ＝確定書類・児童マスタ・監査証跡の決定的ストア（Cloud SQL
  PostgreSQL・Phase 1）。本文は JSON（PG は JSONB）が SSOT・検索キーだけ列昇格・版管理
  （AI 確定/保育士編集を区別）・承認証跡（actor は自己申告注入）。読取は L2/L3 seed（`list_diary_entries`）に
  加え `list_child_record_entries`（指定児の保育経過記録の最新版＝年間マトリクス帳票の過去期埋め込み用。
  列割当・年度の同定は描画側 web/chohyo_pdf の責務＝ここは引くだけ）／`get_document`（単一書類の現行版全文＝本文 entry・
  整形テキスト・確定/編集の区別＝「書類を見る」タブの閲覧・不在/不正 id/未接続は None）。**LLM もパイプラインも呼ばない**
  （永続化はフロント→web API→ここの明示フロー）。`DATABASE_URL` 未設定は降格（書込 skipped・読取 空）。
  表示名→children.id（UUID）の解決はここに1つ。`users`＋`touch_user`（Phase 3）＝IAP の検証済み email を
  初回アクセスで auto-provision（children と同じ流儀・display_name は後から DB で設定・認可は持たない）。
  スキーマ適用は repo root の Alembic（`migrations/`）。clock は外部注入。

## スタブを埋めるとき

場当たりで埋めない。`TODO(設計)` は設計コンテキスト §5/§6/§10 を読んでから既存の型に沿って実装する。
