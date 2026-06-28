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
- **配布リンクのコスト/濫用**：LLM を回す口（`/run`・`/run_sse`・`/run_live`・`/api/improve`）だけを
  `config.demo_passcode`（env `DEMO_PASSCODE`）でゲートする。読み取り・静的配信は素通し。
- **静的資産は `web/static/`（src 配下）に置く**＝Dockerfile は不変（既存 `COPY src ./src` に含まれる）。
  外部 CDN/JS/フォントを読み込まない（ローカル完結）。ビルド工程を足さない（ES モジュール直配信）。
- **実名を出さない**（架空児のみ＝§14）。サンプル投入も架空児・仮メモのみ。

## デザイン規約（刷新後・崩さない）

UI は「Claude Code の見た目の丸写し」でなく、agent UX の**実質**（透明性・状態可視化・HITL・
正直な降格・作業の可視化）を保育士語に翻訳して載せる。方針＝**ハイブリッド**：日誌/月案＝温かく・
回す（improver）＝コンソール調を、**単一デザインシステム**で橋渡しする。

- **色は意味で割り当てる**＝`styles.css` の `:root` トークンが SSOT（面/文字/actor/状態/ゲート/diff）。
  ハードコード色を散らさない。色相を増やさず明度/彩度で差を付ける。状態チップ/ステップのテキストは
  `--state-*-ink`（soft 地で本文 4.5:1 を満たす濃色）を使う（彩度色は図形・縁取り用）。
- **アイコンはインライン SVG**＝`ui.js` の `ICONS` に集約し `iconHTML(name)` で描画（`currentColor`・
  `aria-hidden`）。静的HTMLは `data-ic` プレースホルダ＋`hydrateIcons()`。**装飾絵文字を使わない**。
- **ライト/ダーク**＝`prefers-color-scheme` ＋手動トグル（`data-theme`）。トークンのみ差し替える。
- **a11y**＝本文 4.5:1・タッチ 44px・`:focus-visible` 全要素・`prefers-reduced-motion`・状態は
  色だけに依存させず語＋アイコン併記・モーダルは dialog セマンティクス＋背後 inert。
- **エージェントの可視化**＝actor lane（作成AI/レビューAI/前月の集計/保育士/改善）・計画ステッパー・
  ツールバッジ（call→response で完了表示）・書類パネル（AI下書き→承認で公式記録）・回すはパイプライン
  （提案→競合→評価ゲート→PR、ゲートは PR バッジ色）。**降格/非成功は偽の緑を出さない**（スピナーを止める）。
- whoOf の分岐順は `prep` を `author/monthly` より先に判定（`monthly_prep` の誤分類防止。docflow の
  ステッパー routing と一致させる）。

## 物理マッピング

- `routes.py` … `register_web_ui(app)`（server.py が1回呼ぶ）。`/api/config`・`/api/policy`・
  `/api/eval-baseline`・`/api/gate`＋パスコード middleware。`/` を `/app/` へ着地（dev UI は `/dev-ui/` 温存）。
- `improver_stream.py` … `/api/improve`・`/api/improve/resume`（improver を SSE 駆動・resume 用に
  プロセス内 session 保持。スケールアウト時は共有ストアが要る＝v0 の既知の制限）。
- `static/` … 保育士 SPA。`adk.js`（ADK REST/SSE クライアント）／`docflow.js`（日誌・月案 共通フロー）／
  `improver.js`（回すダッシュボード）／`ui.js`・`app.js`・`styles.css`・`index.html`。

## 入口

- ローカル：`uvicorn server:app` → `http://localhost:8000/app/`（`adk web src` の dev UI は `/dev-ui/`）。
- 配信：Cloud Run の URL ルート（`/`）が `/app/` に着地。`DEMO_PASSCODE` を設定すると要パスコード。
