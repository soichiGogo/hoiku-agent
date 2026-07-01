# web/ ＝ 保育士向け配布 UI（層A・配信の presentation）

ここで Claude がすること：審査員・保育士が**1枚で触れる UI**を提供し、3責務（harness/agents/improver）を
そのまま見せる。生成ロジックは持たない。設計コンテキスト §11（Cloud Run 直ホスト）／北極星。

## 立ち位置（4つ目の責務ではない）

- **薄い presentation 層**。日誌/月案の生成は ADK の `get_fast_api_app` が出す**ネイティブ REST**
  （`/run_sse`・`/apps/{app}/users/{u}/sessions`・`PATCH …/sessions`）をフロント SPA が直接叩く＝
  **自前 Runner を組まない**（server.py の方針・§9）。harness/agents/schemas は不変のまま動く。
- improver（二階）だけは discoverable app でない（root_agent を持たない＝improver/CLAUDE.md）ため、
  `improver_stream.py` が `build_improver_agent` を InMemoryRunner で SSE 駆動する（run_improver.py と同型・
  **別エントリの原則は維持**。一階の root_agent には載せない）。

## 守る制約

- **決定的ロジック・採点を持ち込まない**（実体は harness/eval に1つ＝§5）。ここは描画と中継だけ。
- **HITL は ADK の機構をそのまま使う**：`ask_caregiver`（LongRunningFunctionTool）で止まったら、
  保育士の回答を `function_response` Part として `/run_sse` に再送して invocation を再開する。承認は
  `PATCH …/sessions {state_delta:{caregiver_approved:true}}`（真の承認ゲート＝§9/§13。書き戻し自体は
  確定パイプラインのコールバックが担う）。
- **確定書類の編集（`docedit.js`）も harness 経由で再検査する**：保育士は `state["final_entry"]`（FinalizeAgent が出す
  構造化エントリ）を**標準様式の見た目の編集フォーム**で自由に直せる。保存時は編集後 entry を `POST /api/finalize-edit`
  （harness の `finalize_entry` を中継）で再 validate/整形し、結果を `PATCH …/sessions` で `final_entry`/`final_document`/
  `validation` へ反映する（型成立ゲートを編集後も効かせる）。**validate/整形を JS で再実装しない**（タグ語彙も `/api/form-meta`
  ＝schemas Enum を SSOT に。記録日・対象月は機械メタなので read-only）。承認は従来どおり別アクション（`caregiver_approved`）。
- **配布リンクのコスト/濫用**：LLM を回す口（`/run`・`/run_sse`・`/run_live`・`/api/improve`）だけを
  `config.demo_passcode`（env `DEMO_PASSCODE`）でゲートする。読み取り・静的配信は素通し。
- **静的資産は `web/static/`（src 配下）に置く**＝Dockerfile は不変（既存 `COPY src ./src` に含まれる）。
  **フロントは**外部 CDN/JS/フォントを読み込まない（ローカル完結）。ビルド工程を足さない（ES モジュール直配信）。
  （帳票PDF のサーバ生成＝`chohyo_pdf.py` はバックエンド依存で別軸：reportlab＝純 pip・システムライブラリ不要、
  日本語フォントは `web/fonts/ipaexg.ttf` を**同梱**して埋め込む＝実行時に外部取得しない＝ローカル完結は保つ。）
- **帳票PDF（現場でそのまま綴じる最終形＝§18）は presentation**：確定 entry を園の様式に近い罫線帳票へ描くだけ
  （型の保証・validation は harness＝§5・ここは描画のみ）。欄順は `write_draft`/`write_monthly_draft`（標準様式）と一致させる。
- **実名を出さない**（架空の子のみ＝§14）。対象児・サンプル投入は現場の日誌に寄せた**実在しない仮名**
  （下の名前＋ちゃん/くん・`app.js` の `CHILDREN`）と仮メモのみ（記号名「架空児A」には戻さない）。

## デザイン規約（刷新後・崩さない）

UI は「Claude Code の見た目の丸写し」でなく、agent UX の**実質**（透明性・状態可視化・HITL・
正直な降格・作業の可視化）を保育士語に翻訳して載せる。方針＝**日誌/月案・指針を育てる（improver）を
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
  **指針を育てる**は 指針カード閲覧＋変更履歴／提案カード（確認前→反映済み）→意味的競合の比較相談（`.compare` で既存↔新）→
  保育士決定で即反映（ステッパー＝修正メモ→競合を精査→整合→反映）。**降格/非成功は偽の緑を出さない**
  （スピナーを止める・store の永続性は `store`＝persistent/ephemeral/unavailable で正直表示）。
- **過程は畳む（progressive disclosure）**＝日誌/月案・指針を育てる いずれも作成/レビュー/改善の散文・ツールバッジを
  既定で `<details class="proc">` に収める。日誌/月案で前面に出すのは「不足の確認（HITL の askCard）」と
  「最終下書き＝**標準様式の編集フォーム（`docedit.js`）**＋validation」だけ（確定下書きは読み取り専用でなく**保育士が欄ごとに編集できる**・
  整形テキストはコピー/印刷用に畳んで添える）。指針を育てるの前面は「確認（askCard・比較相談）」と「指針カード」だけ。
  進行はステッパー＋ステータスラインで示す（経過は開けば全部見られる＝透明性は保つ）。
- whoOf の分岐順は `prep` を `author/monthly` より先に判定（`monthly_prep` の誤分類防止。docflow の
  ステッパー routing と一致させる）。

## 物理マッピング

- `routes.py` … `register_web_ui(app)`（server.py が1回呼ぶ）。`/api/config`・`/api/policy`（**指針カード＋履歴＋store**・
  `policy_store.book_view`）・`/api/gate`・**`/api/form-meta`**（タグ語彙＝schemas Enum）・**`/api/finalize-edit`**（編集後 entry を
  harness の `finalize_entry` で再検査・再整形＝中継のみ・LLM 非課金で非ゲート）・**`/api/export-pdf`**（確定 entry を
  `chohyo_pdf.render_pdf` で園の帳票PDFに描いて返す＝描画のみ・非ゲート）＋パスコード middleware（`/api/eval-baseline` は v1 で撤去）。`/` を `/app/` へ着地（dev UI は `/dev-ui/` 温存）。
- `chohyo_pdf.py` … 確定 entry（final_entry）→ 園の様式に近い**帳票PDF**（ReportLab・A4 罫線帳票・日誌/月案）。
  日本語は `web/fonts/ipaexg.ttf`（IPAex ゴシック・再配布可＝IPA Font License v1.0）を埋め込む。描画のみ（§5）。
- `improver_stream.py` … `/api/improve`・`/api/improve/resume`（改善エージェントを SSE 駆動・resume 用に
  プロセス内 session 保持。スケールアウト時は共有ストアが要る＝既知の制限）。中継のみ（ツール payload がカード化されるだけ）。
- `static/` … 保育士 SPA。`adk.js`（ADK REST/SSE クライアント＋`exportPdf`＝帳票PDF取得）／`docflow.js`（日誌・月案 共通フロー・
  確定エリアに「帳票PDFをダウンロード」ボタン＝承認後も残す）／`docedit.js`（確定書類を標準様式の見た目で編集するフォーム＝
  欄ごと入力・タグ多選択・collect()→entry）／`policy.js`（指針を育てる＝カード閲覧＋履歴＋即反映フロー）／`ui.js`・`app.js`・`styles.css`・`index.html`。
- `fonts/` … 帳票PDF に埋め込む日本語フォント（`ipaexg.ttf`＝IPAex ゴシック）＋ライセンス（IPA Font License v1.0）。

## 入口

- ローカル：`uvicorn server:app` → `http://localhost:8000/app/`（`adk web src` の dev UI は `/dev-ui/`）。
- 配信：Cloud Run の URL ルート（`/`）が `/app/` に着地。`DEMO_PASSCODE` を設定すると要パスコード。
