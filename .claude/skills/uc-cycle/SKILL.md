---
name: uc-cycle
description: ユースケース総点検サイクルを 1 件ぶん回す。docs/ユースケース一覧.md（台帳）から未着手 UC を 1 件選び、agent-browser で実アプリ（uvicorn server:app の /app/）を実 LLM 操作して試行→バグがあれば gh issue 起票→codex(最高effort)に plan→実装→Claude サブエージェント(opus 最高effort)が別観点レビュー→pytest/ruff 検証→PR 作成→台帳更新、までを 1 セッションで完結する。重複は台帳の状態で防ぐ。
argument-hint: "[UC-ID | next（既定・未着手を1件）| audit（台帳点検）]"
---

# ユースケース総点検サイクルを回す

実アプリ（保育士向け SPA `/app/`）を **実 LLM で操作** して製品バグを掘り、発見したバグを
**別系統モデル（codex）で修正 → 別モデル（Claude opus サブエージェント）でレビュー → PR** まで
1 セッションで閉じる。台帳 `docs/ユースケース一覧.md` が **重複なく回すための SSOT**。

- 台帳の凡例・重複防止ルール・UC 一覧は `docs/ユースケース一覧.md` を正とする（ここでは手順のみ）。
- **実 LLM・実 GCP 前提**（決定論 E2E は `/e2e`、品質回帰は `/adk-eval`＝別スキル）。creds/枠が無いときは
  fail-warn（試行はスキップし理由を報告。決定論テストだけ回す）。
- ブラウザ操作は **agent-browser skill/CLI**（`agent-browser skills get core|dogfood`）を使う。
  built-in の web ツールより優先（agent-browser skill の指示）。
- 対症療法禁止（AGENTS.md / CLAUDE.md）。バグは根本原因を直す。assertion 緩和で緑にしない。

## 手順

### 0. 作業場所を確定（編集着手前）

- primary checkout は main 据え置き。**この UC 用に main 起点の専用 worktree に入る**
  （`EnterWorktree`。ブランチ名は `uc/<UC-ID>` 目安）。台帳更新も修正もこのブランチに乗せる。

### 1. UC を 1 件選ぶ（重複防止のロック）

1. `docs/ユースケース一覧.md` を読み、引数で対象を決める：
   - `UC-XX` 明示 → その UC。`next`/未指定 → **状態＝未着手** の先頭 1 件。
   - `audit` → 台帳の状態を点検して報告（試行はしない。下記「台帳点検」へ）。
2. 選んだ UC の状態を **`調査中`** に更新し、**即コミット**（`docs: <UC-ID> 調査中`）。
   これで他セッションと重複しない。1 サイクル＝1 UC。

### 2. 実アプリを起動して試行（バグ発見）

1. **環境ブートストラップ**：`bash .claude/skills/uc-cycle/bootstrap.sh`（試行用 worktree の中で実行）。
   下記を冪等に用意する（2026-07-16 の試行で確定した実コマンドを固めたもの）：
   - primary checkout から `.env` をコピー（gitignore 済み・commit 禁止）＋ `uv sync --extra dev`。
   - **ローカル throwaway Postgres を docker で起こし**（既定 5433・5432 は他プロセスと衝突しやすい）、
     `.env` に `DATABASE_URL` 設定 → `uv run alembic upgrade head` → `scripts/seed_documents.py` で
     デフォルト seed（仮名10人・クラス2・確定書類167件）を**既定 workspace**へ投入。
     **DB＋seed が無いと content 系 UC（書類作成/アーカイブ/クラス・園児/初期化）は設計どおり生成を
     ブロックして試せない**（`app.js showMissingRecords`＝「作成に必要な記録を確認してください」＝
     バグでなく正しい降格）。docker/DB を用意しないときは **降格でも試せる UC のみ**（台帳の分類）に絞る。
   - 別途 ADC：`gcloud auth application-default login`（**実 LLM は課金・利用枠 llm_budget を消費**）。
   - 未整備なら fail-warn で報告し、その UC は「環境未整備でスキップ」として台帳にメモを残す。
2. `uvicorn server:app` を起動（バックグラウンド）。ブラウザ操作は **agent-browser CLI**（Bash）で行う：
   - **先に workflow を読む**：`agent-browser skills get core`（基本操作・`@eN` 参照）＋
     `agent-browser skills get dogfood`（探索的テスト/QA/バグハントの型）をロードしてから操作する。
   - `http://127.0.0.1:8000/app/` を開く。**ローカルは Google Sign-In ゲートが無効**（`SESSION_SECRET`/OAuth
     未設定→SPA 直着地・無セッションで既定 workspace を読む）。seed は手順1の CLI で投入済み＝**UI の
     「データを初期化する」ボタンはサインイン＋DB 接続時のみ表示でローカルには出ない**（ボタンに頼らない）。
   - **UC-24（Google ログイン）等の認証 UC はローカルでは試せない**＝デプロイ済み環境が要る（fail-warn で明記）。
3. 台帳の「試行で見る要点」に沿って UC を **実操作**する。期待挙動と実際のズレ＝バグ候補。
   - 崩れ・エラー・不整合・降格の嘘（偽の緑）・様式ズレ・文字化け・HITL 不発火などを観察する。
   - 節目でスクリーンショットを撮り、バグは再現手順とともに証拠として残す。
4. **バグなし** → 状態を `完了`＋`最終確認日` を記入してコミット。余力があれば次の `未着手` へ（手順 1 へ）。
   バグがあれば手順 3 へ。

### 3. issue 起票

- 再現手順・期待/実際・影響範囲（どのタブ/API/層）・関連ファイルを整理し、`gh issue create`
  （日本語・署名なし＝AGENTS.md/CLAUDE.md）。台帳の状態を **`issue #N`** に更新してコミット。

### 4. codex に plan → 実装を依頼（別系統・最高 effort）

- **codex は会話文脈を継承しない**。毎回 前提を明示：cwd（リポジトリルート）・対象ファイル・
  再現手順・受け入れ条件（バグ消失＋既存テスト緑＋対症療法禁止）・`gpt-5.6-sol` 最高 effort。
- まず **plan**（text-only・コード改変させない）で根本原因と修正方針を出させ、批判的に読む。
  設計判断を伴う/非自明なら方針を吟味（必要なら別方針を指示）。
- 次に **実装**（`codex-reply` で継続・workspace-write）。返ってきた patch は**丸呑みしない**。

### 5. 検証（自分で裏取り）

- `uv run --extra dev pytest`（決定論・関連 `tests/test_e2e/` 含む）＋ `ruff check .` ＋
  **`ruff format --check .`**（CI が回すのはこれ。`ruff format .` で整形するだけでなく、CI と同じ `--check` で
  確認する。codex は `ruff check` は通しても `ruff format` を当て忘れることがある＝2026-07-16 の CI fail の学び）。
- 実アプリで **再現が消えたか** を agent-browser で再確認（UI バグなら必須）。
- 落ちたら根本原因を直す（codex に戻すか自分で修正）。緑化のためのテスト改変は禁止。

### 6. 二層レビュー＋対立検証（opus レビュー → codex 判定 → 裁定）

同一系統の自己レビューは「自信ありげな同じ誤り」をなぞる。**別モデル（opus）の指摘 → 別系統（codex）の
妥当性判定 → オーケストレーターの裁定** で、指摘の見逃しと過剰指摘の両方を潰す。

1. **opus レビュー**：`Agent`（subagent_type: general-purpose、model: opus）に diff レビューを依頼：
   根本原因を断っているか・既存設計/レイヤ境界（harness/agents/improver の線）と整合か・
   副作用/退行・テスト網羅・対症療法でないか。**指摘は 1 件ずつ列挙**させる（後段で判定するため）。
2. **codex 判定（対立検証・text-only）**：opus の各指摘を codex（`codex-reply` で継続・コード改変させない）に渡し、
   「この指摘は妥当か（真の問題か／誤検知か／対応不要か）・理由」を **1 件ずつ判定**させる。
   codex は実装本人なので、自己弁護に流れていないかも含めて批判的に読む。
3. **オーケストレーターの裁定（最終判断は自分＝外注しない）**：opus の指摘と codex の判定を突き合わせ、
   各指摘を **要修正／却下（誤検知・スコープ外）／保留（要ユーザー確認）** に分類する。
   - 両者一致で「問題あり」→ 要修正。両者一致で「問題なし」→ 却下。
   - **食い違い**（opus は指摘・codex は妥当性を否定 等）は、自分でコードを読んで裏取りし、
     どちらが信頼できるか根拠を添えて決める。設計判断を伴い自信が持てなければ保留にしてユーザーへ。
4. **修正判断**：要修正が 1 件でもあれば、その指摘だけを codex に実装依頼（前提を明示）→ **手順 5（検証）へ戻る**。
   要修正が無ければ手順 7 へ。指摘・codex 判定・自分の裁定は後で PR 本文/報告に残す（透明化）。

### 7. コミット → PR 作成（台帳更新も同梱）

- 論理単位でコミット（日本語・署名なし）。台帳の状態を **`PR #M`** に更新。
- `gh pr create`（日本語タイトル/本文・署名/宣伝行なし・issue を close 参照）。**PR 作成まで自動**
  （memory: PR 作成〜マージ自律可。ただし auto モードで merge がブロックされたら回避せずユーザーに依頼）。
- 1 サイクル完了。余力と枠があれば次の `未着手` へ（手順 0/1 へ）。

## 台帳点検（引数 `audit`）

- `docs/ユースケース一覧.md` の状態を集計（未着手/調査中/完了/issue/PR/再確認）し、
  **`調査中` のまま放置**（前セッションのロック取り残し）や、マージ済み PR で `再確認` 待ちの UC を洗い出す。
- 製品に新機能タブ/doc_type が増えていたら **UC の抜け**を指摘し、台帳へ追記提案する
  （`docs/architecture.md` の実装状況と突き合わせる）。

## 注意

- **実データ/PII を書かない**（仮名・架空児のみ＝AGENTS.md/CLAUDE.md §14）。issue/PR にも実名を出さない。
- push/PR/merge は外向き。PR 作成は自律可だが、**merge はユーザー確認**（memory 準拠）。
- codex がレート制限/停止なら fail-warn（自分で続行し、その旨・codex の結論・自分の検証を開示）。
- このスキルは実 LLM 層。無料・決定的な制御フロー検証は `/e2e`、品質回帰は `/adk-eval`。
