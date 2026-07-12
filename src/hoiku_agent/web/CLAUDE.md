# web/ ＝ 保育士向け配布 UI（層A・配信の presentation）

`指針を育てる` のカード（参照方針の自然文カードを含む）はすべて同じ表示・同じ改善エージェントの提案→比較相談→即反映フローで育つ（専用の編集エンドポイントは持たない・2026-07-12簡素化）。

ここで Claude がすること：審査員・保育士が**1枚で触れる UI**を提供し、3責務（harness/agents/improver）を
そのまま見せる。生成ロジックは持たない。設計コンテキスト §11（Cloud Run 直ホスト）／北極星。

## 立ち位置（4つ目の責務ではない）

- **薄い presentation 層**。**保育日誌は手入力フォーム**（`diaryform.js`＝AI を通さない・ヒアリング 2026-07：日誌は
  自分の言葉で打つ一次情報の蓄積口）＝クラスの在籍児を空欄で並べ docedit→`/api/finalize-edit`→`/api/records`で保存
  （ADK セッション不使用）。月案（クラス月案）/保育経過記録/要録の生成は ADK の `get_fast_api_app` が出す
  **ネイティブ REST**（`/run_sse`・`/apps/{app}/users/{u}/sessions`・`PATCH …/sessions`）をフロント SPA が直接叩く＝
  **自前 Runner を組まない**（server.py の方針・§9）。harness/agents/schemas は不変のまま動く。
- improver（二階）だけは discoverable app でない（root_agent を持たない＝improver/CLAUDE.md）ため、
  `improver_stream.py` が `build_improver_agent` を InMemoryRunner で SSE 駆動する（run_improver.py と同型・
  **別エントリの原則は維持**。一階の root_agent には載せない）。PolicyBook は共有
  `workspace.resolve_workspace_id` で検証済み request の workspace に束縛し、book_id をLLM引数へ出さない。
  resume は開始時の workspace_id と再開requestを照合してから保育士回答を渡す。

## 守る制約

- **決定的ロジック・採点を持ち込まない**（実体は harness/eval に1つ＝§5）。ここは描画と中継だけ。
- **HITL は ADK の機構をそのまま使う**：`ask_caregiver`（LongRunningFunctionTool）で止まったら、
  保育士の回答を `function_response` Part として `/run_sse` に再送して invocation を再開する。承認は生成後の
  `/api/records/approve` が保存済み現行版をMemory Bankへ同期し、成功後にDBをapprovedへ進める
  （真の承認ゲート＝§9/§13）。ADK state PATCHやパイプラインcallbackで承認・書き戻しを代用しない。
- **確定書類の編集（`docedit.js`）も harness 経由で再検査する**：保育士は `state["final_entry"]`（FinalizeAgent が出す
  構造化エントリ）を**標準様式の見た目の編集フォーム**で自由に直せる。保存時は編集後 entry を `POST /api/finalize-edit`
  （harness の `finalize_entry` を中継）で再 validate/整形し、結果を `PATCH …/sessions` で `final_entry`/`final_document`/
  `validation` へ反映する（型成立ゲートを編集後も効かせる）。**validate/整形を JS で再実装しない**（タグ語彙も `/api/form-meta`
  ＝schemas Enum を SSOT に。記録日・対象月は機械メタなので read-only）。承認は別アクション
  （`/api/records/approve`＝Memory同期＋版単位の承認証跡）。
- **配布リンクのコスト/濫用**：LLM を回す口（`/run`・`/run_sse`・`/api/improve`・
  **`/api/parse-upload`**＝アップロード取込のファイル解析・**`/api/proofread`**＝校正AI）は、
  `harness.llm_budget` が Google Sign-In subject ごとの時間枠と全体の日次枠を原子的に予約してから通す。
  非LLMの書類アーカイブ・名簿・表記ルールは Google Sign-In の workspace 境界で保護する。ADK の dev/builder/memory の書込は
  配布UIから 403 で閉じる。読み取り・静的配信は利用枠を消費しない。**`/run_live`（WebSocket）は撤去**する。
- **アップロード取込（「書類を見る」タブ）は中継のみ**：既存ファイル（PDF/Word/Excel）を既存スキーマへ
  取り込む。フォルダ（種別）から kind、（personal 種別なら）子どもフォルダから child が場所で決まる（別建ての
  種別セレクタを持たない＝ファイルシステム的操作）。フロントは `/api/parse-upload`（multipart）で解析結果 entry を
  受け、**既存の編集フォーム（`docedit.js`）で確認・修正**→ `/api/finalize-edit` で再検査→ `/api/records`
  （`author_kind="imported"`）で保存。**解析・検査・整形・保存の決定的実体は harness/agents に1つ**（web は
  extract〔format 変換〕と中継だけ・§5）。生ファイルは保存しない（抽出→entry のみ永続化＝PII blob を残さない）。
- **書類アーカイブ（Phase 1）は中継のみ**：確定/編集保存/承認のタイミングでフロントが `/api/records`・
  `/api/records/approve` を呼び、実体は `harness/record_store`（web は now 注入だけ＝runtime 境界）。
  actor はヘッダの担当者名入力（自己申告・localStorage・`ui.actorName()`）＝ローカル開発時だけのつなぎ。
  **Google Sign-In（Phase 3）では `auth.py` が検証した session の Google アカウントが actor に優先**され
  （ID token の署名/audience/期限/email_verified と署名付き専用 cookie のログイン CSRF token を検証・users へ auto-provision＝
  `record_store.touch_user`・表示名設定済みなら「表示名（email）」）。`/app/`・API・ADK 口は session 無しで fail-closed。
  **サインイン時はヘッダの担当者欄が「自分の表示名」編集欄**になり、`POST /api/user`（`adk.setUserProfile`）で
  `record_store.set_user_display_name` を叩いて display_name を DB に登録/編集する（email/sub は body でなく Google 検証済み値で
  解決＝偽装不可・未サインインは 403・Google 認証済みの自己書込ゆえパスコードゲート外）。表示は `/api/config` の user_email／user_display_name
  （未登録は email をプレースホルダに出して登録を促す・未サインインは従来の自己申告＋localStorage）。
  **アーカイブの失敗で本流（state 保存・承認）を壊さない**が、skipped/error は表示行で正直に出す（偽の緑を出さない）。
  子ども選択肢は入力式コンボボックス（`app.js` の `childCombo`＝前方一致の候補＋Tab/Enter/クリックで補完・
  30人規模でもスケール。チップ全列挙は廃止）。候補ソースは `/api/children`（児童マスタ）があればそこから
  （誕生日があれば年齢帯 0-2/3-5 を満年齢で自動判定＝`ageBandOf`）・無ければ従来の仮名ロスターへ降格。
  **未登録名を選ぶと新規児登録フォームをコンボ直下に開く**（`onAddChild`）＝本名（姓/名）＋性別を入力し、
  呼び名（名）＋敬称（**性別導出＝男くん/女ちゃん固定**・`composeDisplayName` は harness の
  `compose_display_name` と一致）＝display_name を合成→`POST /api/children`。敬称の「くん/ちゃん問題」は
  性別セレクタで一意化し入力ゆれ・重複児を構造で防ぐ。**本名（姓名）は氏名欄用で DB のみ・§14**（eval/seed は
  仮名のまま）。アーカイブ未接続はセッション内だけ選択肢に足す（本名/性別は保存されず氏名欄は呼び名へ降格）。
- **静的資産は `web/static/`（src 配下）に置く**＝Dockerfile は不変（既存 `COPY src ./src` に含まれる）。
  **フロントは原則**外部 CDN/JS/フォントを読み込まない（ローカル完結）。ただし案内画面の Google Sign-In 公式ボタンだけは
  Google が配布する `https://accounts.google.com/gsi/client` を例外として読む（独自ボタンではブランド/仕様に追随できないため）。
  ビルド工程を足さない（ES モジュール直配信）。
  （帳票PDF のサーバ生成＝`chohyo_pdf.py`（日誌/月案/クラス月案/保育経過記録/保育要録）はバックエンド依存で別軸：reportlab＝純 pip・システムライブラリ不要、
  日本語フォントは `web/fonts/ipaexg.ttf` を**同梱**して埋め込む＝実行時に外部取得しない＝ローカル完結は保つ。）
- **帳票PDF（現場でそのまま綴じる最終形＝§18）は presentation**：確定 entry を園の様式に近い罫線帳票へ描くだけ
  （型の保証・validation は harness＝§5・ここは描画のみ）。日誌/月案の欄順は `write_draft`/`write_monthly_draft`（標準様式）と
  一致させる。**保育経過記録は年間マトリクス様式（実様式準拠）**＝A4 横・行＝領域（0–2:3視点/3–5:5領域＋その他）×列＝4期で、
  今回の期に加え**過去期の列はアーカイブの保存済み保育経過記録から自動で埋める**（routes が `record_store.list_child_record_entries`
  で引き、列割当は `assign_period_columns`＝純関数：同じ子・同じ年度のみ・今回の entry が常に優先・期が読めないものは除外。
  未接続/該当なしは今回の期のみ＝空欄の罫線で手書き追記可）。テキスト版（`write_child_record_draft`）は期の縦型＝コピー用で役割分担。
- **実名を出さない**（架空の子のみ＝§14）。対象児・サンプル投入は現場の日誌に寄せた**実在しない仮名**
  （下の名前＋ちゃん/くん・`app.js` の `CHILDREN`）と仮メモのみ（記号名「架空児A」には戻さない）。

## デザイン規約（刷新後・崩さない）

UI は「Claude Code の見た目の丸写し」でなく、agent UX の**実質**（透明性・状態可視化・HITL・
正直な降格・作業の可視化）を保育士語に翻訳して載せる。方針＝**日誌/月案/保育経過記録・指針を育てる（improver）を
すべて温かく**、**単一デザインシステム**で統一する（v1 でコンソール調は撤去）。

- **色は意味で割り当てる**＝`styles.css` の `:root` トークンが SSOT（面/文字/actor/状態/ゲート/diff）。
  ハードコード色を散らさない。色相を増やさず明度/彩度で差を付ける。状態チップ/ステップのテキストは
  `--state-*-ink`（soft 地で本文 4.5:1 を満たす濃色）を使う（彩度色は図形・縁取り用）。
- **アイコンはインライン SVG**＝`ui.js` の `ICONS` に集約し `iconHTML(name)` で描画（`currentColor`・
  `aria-hidden`）。静的HTMLは `data-ic` プレースホルダ＋`hydrateIcons()`。**装飾絵文字を使わない**。
- **ライト/ダーク**＝`prefers-color-scheme` ＋手動トグル（`data-theme`）。トークンのみ差し替える。
- **a11y**＝本文 4.5:1・タッチ 44px・`:focus-visible` 全要素・`prefers-reduced-motion`・状態は
  色だけに依存させず語＋アイコン併記・モーダルは dialog セマンティクス＋背後 inert。
- **エージェントの可視化**＝actor lane（作成AI/レビューAI/前月の集計/保育士/改善）・計画ステッパー・
  ツールバッジ（call→response で完了表示）・書類パネル（AI下書き→**標準様式の編集フォームで保育士が欄ごとに編集**→承認で公式記録）。
  **レビュー巡回（authoring_loop）の差し戻しはステッパーで可視化する**＝reviewer が NEEDS_REVISION を返し作成AIが再作成へ
  戻ったとき（review 直後に draft が来たら差し戻しと判定・`docflow.js` の `phaseKindOf`／`stepper.rewindTo`）、ステッパーを
  「下書き」へ巻き戻して再点灯し「レビュー」に周回バッジ（`N/最大M`＝`stepper.badge`・M は `/api/config` の
  `max_review_iterations`＝harness `MAX_REVIEW_ITERATIONS` の SSOT）を添える。承認一発（round=1）では出さない
  （gate/finalize は draft と誤分類せず偽の差し戻しを起こさない）。
  **指針を育てる**は 指針カード閲覧＋変更履歴／提案カード（確認前→反映済み）→意味的競合の比較相談（`.compare` で既存↔新）→
  保育士決定で即反映（ステッパー＝修正メモ→競合を精査→整合→反映）。**降格/非成功は偽の緑を出さない**
  （スピナーを止める・store の永続性は `store`＝persistent/ephemeral/unavailable で正直表示）。
- **過程は畳む（progressive disclosure）**＝日誌/月案・指針を育てる いずれも作成/レビュー/改善の散文・ツールバッジを
  既定で `<details class="proc">` に収める。日誌/月案で前面に出すのは「不足の確認（HITL の askCard）」と
  「最終下書き＝**標準様式の編集フォーム（`docedit.js`）**＋validation」だけ（確定下書きは読み取り専用でなく**保育士が欄ごとに編集できる**・
  整形テキストはコピー/印刷用に畳んで添える）。指針を育てるの前面は「確認（askCard・比較相談）」と「指針カード」だけ。
  進行はステッパー＋ステータスラインで示す（経過は開けば全部見られる＝透明性は保つ）。

## 物理マッピング

- `routes.py` … `register_web_ui(app)`（server.py が1回呼ぶ）。`/api/config`・`/api/policy`（**指針カード＋履歴＋store**・
  `policy_store.book_view`）・`/api/gate`・**`/api/form-meta`**（タグ語彙＝schemas Enum）・**`/api/doc-template`**（様式テンプレート＝本文セクションの順序/ラベル/種別＝`template_store.book_view`・編集フォームが使う・読取非ゲート・壊れは空で 200）・**`/api/finalize-edit`**（編集後 entry を
  harness の `finalize_entry` で再検査・再整形＝中継のみ・LLM 非課金で非ゲート）・**`/api/export-pdf`**（確定 entry を
  `chohyo_pdf.render_pdf` で園の帳票PDFに描いて返す＝描画のみ・非ゲート。保育経過記録は同じ子の保存済み保育経過記録を
  アーカイブから引いて past_entries で渡す＝年間マトリクスの過去期埋め込み・未接続は降格。**保育経過記録/要録の氏名欄は
  児童マスタの本名（姓＋名＝`record_store.get_child` の official_name）を `official_name` で渡して描く**＝就学先引継ぎの
  公式様式は本名（AI 非生成・未登録は呼び名へ降格））・**`/api/export-docx`**（確定 entry を
  `docx_fill.fill_docx` で園の実 Word 様式に流し込んで返す＝Word 編集版・描画のみ・非ゲート・未対応 kind は 400。対応 kind は
  `/api/config` の `docx_kinds` で UI に伝えボタン出し分け）・**`/api/parse-upload`**（アップロード取込＝multipart で
  受けたファイルを `upload_parse.parse_uploaded_file` で解析し確認・編集用 entry〔＋整形/検査結果〕を返す中継。**LLM を回す口＝
  `llm_budget` で利用枠を予約**・未対応形式/種別は 400・creds 無/LLM 失敗は 200＋parse_error で正直に降格。保存は後段の
  `/api/records`＝`author_kind="imported"`）・**`/api/records`／`/api/records/approve`（DB現行版を
  `harness.memory_writeback` で子ども別fact化→Memory同期完了後にapproved。接続済み障害は503で承認保留、
  `memory_synced_version_id` で同じ版の二重投入防止）／
  `/api/records/diary-entries`／`/api/records/diary-meta`（期間内の日誌メタ＝id・対象日・年齢帯・評価充足＝クラス月案の評価未記入検出用・リテラル路）／
  `/api/records/class-monthly-seed`（クラス月案 seed 3系統＋在籍児名簿 class_roster＝`record_store.class_monthly_seed_inputs` の中継・依存モデル 2026-07・非ゲート）／
  `/api/records/child-record-entries`（全期・`exclude_period` で作成対象の期を除外＝要録 L4／保育経過記録「前回まで」seed）／
  `/api/records/feedback`（**書類フィードバック＝👍👎＋ひとこと**＝`record_store.save_feedback`/`list_feedback` の中継・POST 保存は
  Google Sign-In の workspace 境界・actor は `_resolve_actor`／GET 一覧は読取素通し・リテラル路なので `/api/records/{id}` より前に宣言）／
  `/api/records/{id}`（単一書類の現行版全文＝「書類を見る」タブ・`record_store.get_document`・不在/不正 id は 404・
  リテラル路 diary-entries/diary-meta/feedback より後に宣言し優先させる）／`/api/children`**（GET＝児童マスタ一覧／**POST＝新規児登録**＝本名（姓/名）＋
  性別を受け、呼び名＋敬称＝display_name を harness が合成し `upsert_child`。書類アーカイブ＝`harness/record_store` の中継・now 注入のみ・
  **書込＝Google Sign-In の workspace 境界で保護**・読み取りは素通し・名空/性別不正=400）・**`POST /api/user`**（サインイン中
  ユーザー自身の表示名を **Google 検証済み email/sub に紐づけて**設定＝`record_store.set_user_display_name` 中継・body 由来を使わず偽装不可・
  未サインインは 403・Google 認証済みの自己書込）・**`/api/notation`**（ひらがな表記DX＝`harness/notation_store` の
  CRUD 中継・GET一覧/POST追加/PATCH編集/DELETE削除・now 注入＋version 楽観ロックの read-modify-write・**書込は公開デモの
  Google Sign-In の workspace 境界で保護**・読取は素通し・種別不正=400/重複競合=409）＋利用枠 middleware（`/api/eval-baseline` は v1 で撤去）。`/` は案内画面を返す（dev UI は `/dev-ui/` 温存）。
- `workspace.py` … 署名付き Google session の subject から `record_store.touch_user` を通じて workspace_id を
  解決する共有認可境界（`provision_user`／`resolve_user`／`resolve_workspace_id`）。routes と improver_stream が
  共用し、request body・LLM出力から workspace を受けない。**初回ログイン（touch_user が新規 workspace を作った
  呼び出し＝workspace_created）では `harness.demo_seed.seed_workspace` でデフォルト seed（クラス・園児・確定書類
  チェーン）をその場で投入**＝初見でも全タブを体感できる。seed 失敗はログイン本流を壊さない（warning＋続行）。
  ヘッダの**「データを初期化して始める」ボタン**（`app.js` の `#reset-data`・サインイン＋アーカイブ接続時のみ表示）は
  `POST /api/account/reset`＝`demo_seed.reset_workspace`（書類・園児・クラス・フィードバック・指針/表記カスタムを
  即時消去→seed 再投入・User/Workspace/利用枠は残しログイン継続）。成功時は workspace 単位の完了印を
  `localStorage` に保存し、同じブラウザでは再読込後もボタンを再表示しない（一回限りの開始導線）。**アカウント削除の受付
  （`POST /api/account/deletion-request`＝30日遅延）は API として温存・UI からは外した**（privacy.html は
  問い合わせベースの記述）。
- `chohyo_pdf.py` … 確定 entry（final_entry）→ 園の様式に近い**帳票PDF**（ReportLab・日誌/個別月案/保育要録＝A4 縦・保育経過記録＝**A4 横の年間マトリクス**（行=領域×列=4期・担任印ヘッダ・身長体重欄・期→列は period 先頭の年月で決定/不明は先頭列・過去期の列は past_entries＝アーカイブの保存済み保育経過記録で自動埋め＝`assign_period_columns`）・**クラス月案＝A4 横で園フォーム（月間指導計画）を再現**（`_class_monthly_story`＝ヘッダ〔年度・月/クラス/担任・園長・主任印〕＋保育目標・先月の姿・行事・保護者支援＋区分×領域グリッド〔養護/教育を rowspan〕＋食育/健康・安全/家庭/職員の連携＋0–2 は個人目標小表＋評価系の空欄。園の docx が横向きのため横で描く＝`_LANDSCAPE_KINDS`））。**保育経過記録/要録の氏名欄は `render_pdf(..., official_name=)` で本名（姓＋名）を描く**（呼び名＋敬称でなく＝公式様式・routes が児童マスタから解決・未指定は child_id へ降格）。
  **線形様式（日誌/個別月案/要録）の本文セクション順序・ラベルは `template_store` から駆動**（テキスト整形と共通の SSOT・種別→flowable は chohyo_pdf が持つ）。保育経過記録マトリクス・クラス月案グリッドは非線形のため対象外（各 story wrapper のコード）。
  日本語は `web/fonts/ipaexg.ttf`（IPAex ゴシック・再配布可＝IPA Font License v1.0）を埋め込む。描画のみ（§5）。
- `docx_fill.py` … 確定 entry → **園の実 Word 様式（`web/templates/*.docx`）へ流し込んだ .docx**（`fill_docx(kind, entry)`＝
  python-docx で見出し語からセルを同定して埋める）。帳票PDF が「綴じる確定版」なのに対し**Word 編集版**（保育士が Word で
  微修正・印刷）。純 pip・システムライブラリ不要＝Dockerfile 不変（雛形は `web/templates/` 同梱・実行時に外部取得しない）。
  **docx→PDF のサーバ変換はしない**（重い依存を持ち込まない）。描画のみ（型の保証は harness＝§5）。配線済み＝保育経過記録
  （5領域×子どもの姿）／**クラス月案（`_fill_class_monthly`＝園フォームの全欄を直接埋める＝保育目標・先月の姿・
  区分×領域グリッド・食育/健康・安全/家庭/職員の連携・0–2 は個人目標小表を登場児ぶん・不足行は add_row。評価系は
  月末記入で空欄温存＝§18）**／個別月案（旧経路＝個別出力を「個人目標」小表へ写像・クラス欄は保育士記入で温存・
  0-2 フォームのみ小表あり・3-5 はヘッダのみ）／保育要録（公式様式＝こども家庭庁 保育所児童保育要録の「保育に関する記録」の
  括弧ラベル直下＋列4へ追記・ラベルは残す）。`_FILLERS` に kind 追加で拡張。
  **末尾に確認印欄（担任/主任/園長）**を置き公式記録の体裁にする。生活記録の4列表は本文全幅で罫線をそろえる
  （ReportLab の Table 既定 hAlign=CENTER のズレを LEFT＋全幅で是正）。ヘッダの気温・組は `DiaryEntry` の任意欄（記入時のみ）。
- `auth.py` … Google Identity Services の popup callback（案内画面と同一Originの `POST /auth/google`）を受け、ID token を
  Google の公開鍵で検証し（audience/期限/email_verified）、案内画面が発行する**署名付き専用 cookie のログイン CSRF token**
  （header との double-submit）を確認して最小 identity（sub/email/name）だけを署名付き session に保存する。**有効な cookie の
  token は再描画で使い回す＝回転させない**（favicon 等の自動リクエストや別タブの再描画で回転させると、表示中ページの token と
  cookie が食い違い正しいログインまで拒否する＝2026-07 の本番障害）。
  `/` は案内画面、`/favicon.ico` は公開アセット、`/app/`・API・ADK 口は routes の middleware が session 無しで拒否する
  （Sec-Fetch-Mode≠navigate のサブリソース要求は案内へ redirect せず 401＝post_login_path の汚染防止）。Google の公式ボタンを
  描くため案内画面だけ `accounts.google.com/gsi/client` を読む（通常の UI 資産は従来どおりローカル配信）。
- `improver_stream.py` … `/api/improve`・`/api/improve/resume`（改善エージェントを SSE 駆動・resume 用に
  プロセス内 session 保持。スケールアウト時は共有ストアが要る＝既知の制限）。中継のみ（ツール payload がカード化されるだけ）。
- `upload_extract.py` … アップロードされたファイル（bytes）→ LLM 入力コンテンツへの**決定的**変換
  （`extract_upload`＝docx: python-docx／xlsx: openpyxl でテキスト抽出・pdf: `inline_data` で Gemini マルチモーダルへ生 bytes・
  `to_parts` で genai Part 化）。`chohyo_pdf`/`docx_fill` と同じ「web の純粋なフォーマット変換」＝中身の解釈は持たない。未対応形式/空/過大は ValueError。
- `upload_parse.py` … アップロード取込の実体（`parse_uploaded_file`）。extract →（`build_upload_parser_agent` を
  InMemoryRunner で1パス駆動＝improver_stream と同型・SSE 無しの一発）→ 対象キー/child/age_band を保育士入力で
  **権威的に上書き**→ `finalize.extract_json_block`→`finalize_entry` で検査・整形（決定的実体は harness）。creds 無/LLM 失敗は正直に error 降格。
- `proofread.py` … 校正AI（日本語チェック・言い換え提案）の実体（`proofread_entry`／`collect_items`）。手入力 entry から
  **叙述文（プロース系）だけ**を id/パス/ラベル付きで集め（数量的な生活記録・仮名・タグ・日付は渡さない＝AI に事実を
  触らせない・§14）、`build_proofreader_agent` を InMemoryRunner で1パス駆動→```json フェンスの提案を復元→**id→entry の
  パスへ写像**して返す（元と同一/空/対象外 id は落とす安全網）。中継のみ（採否・反映は front・提案の実体は agents）。
  `/api/proofread`＝LLM 口＝`llm_budget` で利用枠を予約・creds 無/LLM 失敗は 200＋error で正直に降格（そのまま保存できる）。
- `static/` … 保育士 SPA。**上位タブは4つ**：**書類を作る**（日誌/クラス月案/保育経過記録/保育要録を**カテゴリ別グループ表示の種別メニュー**。
  保育経過記録の対象期間は年度4期・各3か月固定で、`/api/config` が返す `child_record_periods` を
  単一セレクタに描く。開始・終了の二重入力やフロント独自の終了月計算は持たない）
  （`app.js` の `DOC_CATEGORIES`＋`renderDocMenu`）で1タブに統合＝4カテゴリ〔指導計画/保育記録/保護者連携/園運営〕に分け、対応済み（DOC_TYPES に
  フロー実体あり）は選択可・**今後対応予定（年間指導計画/週案/日案/連絡帳/おたより/勤務シフト）は灰色の非選択 placeholder〔status="soon"・クリックで一言案内・
  生成しない＝ロードマップ提示〕**。ready item の label/icon は DOC_TYPES から引く〔二重管理しない〕）で切替。**保育日誌は手入力フォーム**（`diaryform.js`＝クラス選択→在籍児 roster を空欄で並べる＝AI を通さない・needsChild=false。
  クラス未登録/DB 未接続は年齢帯チップへ降格・記録日は既定=今日）／月案/経過記録/要録は共通の ADK フロー（`docflow.js`）。
  バックエンドの `DocTypeRouter`＝doc_type 分岐と 1:1〔日誌は載らない〕。**月案セグメントはクラス月案に一本化**）／**育てる**／
  **クラス・園児**（園の名簿管理＝`classes.js`・クラス定義＋園児登録/割当・日誌 roster の素）／**書類を見る**（アーカイブ閲覧）。**「育てる」は2サブタブ（`.subtab`/`.subpanel`＝`setupSubTabs`）＝
  「指針を育てる」（agentic な勘所）｜「表記ルール」（決定的な統一）**。仕組みは分離のまま（policy_store と notation_store・§5）で、
  保育士から見た「書類作成に教え込む場所」を1タブに集約する presentation の統合（②）。**「指針を育てる」には対象書類セレクタ**（`app.js` の
  `POLICY_TARGETS`＝すべて/共通/日誌/月案/保育経過記録/要録・PolicyScope と 1:1）を置き、選ぶとデッキ（いまの指針カード）を「共通＋その書類」に
  絞り込み（`policy.setFilter`＝`render_for_doc` の前置注入範囲と一致）、`/api/improve` に `target_scope` を送って提案 scope の既定にする
  （反映先の可視化・改善AIは既定として尊重しつつ内容的に共通と判断したら ask で提案＝勝手に変えない）。ファイル＝`adk.js`（ADK REST/SSE クライアント＋`exportPdf`＝帳票PDF取得＋`listRecords`/`getRecord`＝アーカイブ読取＋`saveFeedback`/`listFeedback`）／`scopes.js`（doc kind→PolicyScope の唯一の対応表＝`POLICY_SCOPE_OF`・docflow の「指針を取り込む」絞りと feedback の target_scope で共用＝二重定義を作らない）／`feedback.js`（**確定/承認画面・アーカイブ詳細に置く 👍👎＋ひとことの軽量フィードバック導線**＝送信で `/api/records/feedback` に文書＋版で紐付け保存・ひとことがあれば「この気づきを指針に活かす」で**インラインに `makePolicy` を再インスタンス化**して改善エージェントを回す〔提案→比較相談→即反映＝育てるタブと同じ描画を再利用・二重実装しない〕・降格safe）／`docflow.js`（日誌・月案・保育経過記録 共通フロー・PREP_META で集計 prep の digest キー/文言を切替・
  `onBusy` で生成中に種別セグメントを固定・確定エリアに「帳票PDFをダウンロード」＋対応 kind のみ「Word様式でダウンロード」ボタン＝承認後も残す・**`.doc-actions` に feedback バーを設置＋アーカイブ保存/編集/承認で document_id を保持**）／`docedit.js`（確定書類を標準様式の見た目で編集するフォーム＝
  欄ごと入力・タグ多選択・collect()→entry。**本文セクションの順序/ラベルは `/api/doc-template`（様式テンプレート）から駆動**＝ヘッダ・widget・collect はコード・
  未取得は既定順フォールバック。**クラス月案（buildClassMonthly）は非線形の園の実様式ルック**＝罫線の区分×領域グリッドを実 `<table>`＋
  セル内テキストエリアで描き〔養護/教育を rowspan・グリッド定義は `CLASS_GRID_ROWS`＝schemas の GRID_ROWS と同順〕、
  0–2 は個人目標を追加/削除可・評価系は月末記入欄＝保育士が普段の月案の感覚で確認・修正できる〔§18〕）／`policy.js`（指針を育てる＝カード閲覧＋履歴＋対象書類フィルタ＋即反映フロー）／`notation.js`（表記ルール＝
  `/api/notation` の CRUD UI・変換元→変換先の一覧・有効/無効トグル・インライン編集・保存先の永続性を正直表示）／`records.js`（書類を見る＝**ファイルシステム風ツリー explorer**：
  `GET /api/records` のメタ一覧（本文なし・軽い）を1回引き、**種別→子ども→書類**の階層をクライアント側で組む（左＝ツリー／右＝内容の2ペイン・`.fs*`）。
  **表示に必要な分だけ読む最適化**＝フォルダは折りたたみ既定で初期描画は種別フォルダのみ・展開したフォルダの DOM だけを都度組む／書類本文（重い＝整形テキスト＋entry）は
  **ファイルを開いたときだけ** `GET /api/records/{id}` を引き**セッション内はキャッシュ**（再クリックは再取得しない）／展開状態は再読込を跨いで保持・本文キャッシュはタブ再オープンで捨て最新を正とする。
  選ぶと現行版の整形テキスト＋帳票PDF ボタンを右ペインに描く。**読取専用ではなく編集・（再）承認もできる**＝右ペインの
  「編集する」で `docedit.js` の編集フォームを開き `finalizeEdit`→`saveRecord(author_kind="caregiver")`＝新版を積む（`mountEditor` を取込確認と共用）、
  未承認なら「承認する」で `approveRecord`。**承認済みを編集すると承認は失効し finalized へ戻る**（record_store が demote・偽の緑を出さない）。未接続/空/障害は正直に降格。
  **外から特定書類を編集モードで開く `openDoc(id,{edit,focus})` を公開**（`{init, refresh, openDoc}`）＝クラス月案作成時の「評価未記入の日誌へ飛んで記入」導線（下記）が使う。
  **対象児フィルタ（`fs-filter`・2026-07-12）**＝日誌・クラス月案はクラス全体（複数児）の記録が1書類に同居し中を
  開かないと特定児の記述と分からないため、書類メタの `children`（登場する子ども全員の表示名＝`record_store` が
  保存のたびに現行版へ同期する索引・migration 0014）を部分一致でクライアント側フィルタし、既存の種別→子ども
  ツリーをそのまま絞り込む（該当種別のみ表示・自動展開・サーバ往復なし＝メタ一覧は既に全件取得済み）。候補
  （datalist）は `adk.getChildren()`（`/api/children` 全件・卒園児や未登場の子も含む）。
  **アップロード取込**＝4種別フォルダを常時表示（空でも取込先）し、各フォルダ（＋personal 種別の子フォルダ）を開くと先頭に「取り込む」行を出す
  ＝場所から kind〔＋child〕が決まる。押すと右ペインに取込フォーム（対象キー/年齢帯/対象児/ファイル・D&D 可）→`adk.parseUpload`（`/api/parse-upload`）→
  **既存 `docedit.js` の編集フォームで確認・修正**→`finalizeEdit`→`saveRecord(author_kind="imported")`→`loadTree`。取込先が未接続（store≠ok）のときは取り込めない〔正直に降格〕）／`ui.js`・`app.js`（**クラス月案作成時に前月・当該クラスの日誌で評価・反省が未記入のものを `getDiaryMeta`〔`/api/records/diary-meta`〕で検出し「N/D を記入」チップを出す＝`checkPrevMonthEvaluations`。チップは `switchTab("records")`＋`records.openDoc(id,{edit,focus:"evaluation"})` で当該日誌の評価欄へ飛ぶ＝生成はブロックしない。決定B〔評価をクラス月案の集計に反映〕の記入を促す動線**）・`styles.css`・`index.html`。
- `fonts/` … 帳票PDF に埋め込む日本語フォント（`ipaexg.ttf`＝IPAex ゴシック）＋ライセンス（IPA Font License v1.0）。
- `templates/` … `docx_fill` が流し込む**園の実 Word 様式（空欄フォーム・PII なし）**：`child_record.docx`（保育経過記録）・
  `monthly_0_2.docx`／`monthly_3_5.docx`（月間指導計画）・`nursery_record.docx`（保育要録）。`COPY src ./src` で同梱＝実行時に外部取得しない（ローカル完結）。

## 入口

- ローカル：`uvicorn server:app` → `http://localhost:8000/app/`（`adk web src` の dev UI は `/dev-ui/`）。
- 配信：Cloud Run の URL ルート（`/`）が案内画面を返し、Google Sign-In 後に `/app/` を開く。LLM 口は利用枠で保護する。
