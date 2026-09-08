> 共通指示の正本は本 AGENTS.md。CLAUDE.md は @AGENTS.md の読み込み入口。詳細は指定された時点で参照し、旧入口へ本文を複製しない。

概要・北極星・技術スタック・ディレクトリ構成・セットアップは @README.md を参照（重複させない）。
レイヤとコードの対応は @docs/architecture.md を参照。

# このプロジェクトの正（SSOT）と設計判断

- **参照配線（2026-07-11・2026-07-12簡素化）**：書類ごとの参照方針は専用カード種別でなく、他の指針カードと同じ自然文の1枚（PolicyScope 別）として書く（例:「保育経過記録の作成では、対象期間の保育日誌と、前回までの保育経過記録すべてを参照する」）。author/reviewer は `fetch_reference` で seed 候補を agentic に取得し `reference_manifest` に実績を残す。固定 digest 注入と pipeline 常設 prep は使わない。seed API/state key/workspace 境界は不変。チェックボックス式の構造化トグルUI（旧 `reference_policy`/`ReferenceRule`）は撤去し、改善エージェントの提案→比較相談→即反映フローで育てる（UXの単純さを精度より優先＝ユーザー判断）。

- **最終的な正は Obsidian vault `google-cloud-hackathon` の `設計/プロダクト方針.md`（製品方針）と
  `設計/エージェント設計.md`（アーキ）**。リポジトリ外にあり Claude からは読めない。
- **リポジトリ内の設計参照は `docs/設計コンテキスト.md`（開発ハンドオフの凝縮版）→ `docs/architecture.md`
  （コード対応）の順に見る**。なお不明なら推測で埋めずユーザーに確認。両者が食い違ったら vault が正。
- コード内の docstring は設計コンテキストの節番号（§4＝アーキ全体像 / §5＝責務境界 / §6＝作成AI /
  §7＝レビューAI / §8＝改善エージェント / §9＝メモリ / §10＝スキーマ / §12＝eval / §19＝ヒアリング反映
  2026-07：保育経過記録＝L3 集積・全年齢化）を参照する。崩さない。
- **構造・規約を変えたら本 AGENTS.md と `docs/architecture.md` を同じ変更内で更新する**（規約と実態の乖離・
  リンク切れを防ぐ。改名・移動・SSOT の置き場変更は特に）。
- **README の図解は `docs/diagram-specs.md` で内容を定義し、同名の `.drawio` を編集可能な正本、`.png` を掲載用の
  派生成果物とする**。画像パーツは `docs/diagram-assets/` に分離し、製品アイコンは公式素材、生成 AI は文字・ロゴ・
  矢印を含まない固有イラストだけに使う。責務境界やデータフローを変えたら仕様・draw.io・PNG を同じ変更内で同期する。

# 開発コマンド

開発・検証・環境構築の前に [エージェント開発手順.md](エージェント開発手順.md) を必ず読む。

# アーキ＝3責務（実装で混ぜてはいけない線。詳細は各層の AGENTS.md）

1. **harness/（決定的・型の保証）** — 必須欄・年齢分岐・順序・集積・**doc_type分岐（router）**・指針カードストア・
   **表記正規化（ひらがな表記DX＝`notation_store`）**・**様式テンプレート（本文レイアウトのデータ＝`template_store`。
   章立て・ラベル・出し分けを JSON に外出しし、テキスト整形（draft.py）・帳票PDF・編集フォームの3レンダラが共通で歩いて描く
   ＝§18 の園差をテンプレ編集で吸収・レイアウトの三重管理を解消・整形実体は harness）**。
   LLM を呼ばない。**決定ロジックの実体はここに1つだけ**。
   （文書作成指針の agent への提示は author/reviewer の InstructionProvider＝`agents/instructions.py` が harness の
   `render_for_doc` を prompt 冒頭へ注入＝薄い組み立て。決定ロジック実体は harness の policy_store／aggregate に1つ。）
   `tools/validate_fields.py`・`tools/write_draft.py` は これを呼ぶ**薄いラッパ**（二重実装しない）。表記の統一は
   soft な指針カードでなく決定的正規化（確定時に取りこぼしなく適用＝型/表記の保証）＝別の道具（線を混ぜない）。
   Memory 書き戻しは**保存済み現行版に対する保育士の明示承認＋型成立**でのみ
   `/api/records/approve` から発火する（`harness/memory_writeback.py` が事実欄だけを子ども別 fact 化。
   接続済みの失敗は承認を fail-closed、未接続は降格。同期済み版は migration 0013 で保持）。
2. **agents/（agentic・中身の決定）** — author（日誌）/ monthly_author（月案）/ child_record_author（保育経過記録）/
   nursery_record_author（保育要録）＝**単一 LlmAgent**（内部を多層化しない。巡回＝再作成は harness の
   `build_authoring_loop` が [作成→レビュー→ゲート] に包んで担う＝NEEDS_REVISION で author が指摘点を再作成）、
   reviewer＝Evaluator（日誌/月案/保育経過記録/保育要録で共用・開示前提の表現観点を含む）。巡回制御・早期終了は harness 側。
3. **improver/（二階・回す）** — 修正メモ→育つ指針カードの追加/改訂または参照資料の既定変更を自走提案。**既存カードとの意味的競合を
   精査し、競合は保育士に比較相談、保育士の決定で即反映**（add/supersede。番人＝意味的競合精査＋保育士決定）。
   指針編集の決定的実体は harness/policy_store（「回した証拠」＝カード内蔵の変更履歴）。**eval は取り込みから外す**
   （CI の品質回帰として温存＝decouple）。

**メモリ3分類**: 子ども長期記憶＝Agent Engine Memory Bank（repo外）／ 育つ指針＝構造化カード
（runtime の正は `DATABASE_URL` 設定時 **Cloud SQL の policy_books 1行（book 丸ごと JSONB・version 楽観ロック）**
＝書類アーカイブと同じ DB へ統合（Phase 2・GCS は廃止）。未設定はローカル `knowledge/文書作成指針.json`＝
git はシード（DB 行不在時のフォールバックシードも兼ねる）。**agent への提示＝author/reviewer の InstructionProvider
（`agents/instructions.py`）が作る書類（doc_type）の scope に合わせ共通＋当該書類の勘所を prompt 冒頭へ前置注入**
（作成/レビューAI は自発的な read_policy 呼び出しでなく与件として動く。§5＝決定的に用意できる指針は harness の
`render_for_doc` を注入する。旧 read_policy ツールは撤去）、improver が保育士決定で即反映）／
静的知識＝Vertex RAG（`knowledge/保育所保育指針/` は gitignore のRAGソース）。
「全部ファイルベース」にしない。なお **表記ルール辞書（ひらがな表記DX＝`notation_store`・`notation_books` 1行・
migration 0004・未設定はローカル `knowledge/表記ルール.json` シード）** は "メモリ" ではなく決定的な表記統一の
辞書（保育士が編集・harness が確定時に適用）＝育つ指針カードとは役割が別（agentic な勘所 vs 決定的な表記）。

# コード規約（このリポジトリ固有）

- 各モジュール冒頭に `from __future__ import annotations` を置く。
- ADK エージェントは **`build_xxx()` ファクトリ関数**で構築して返す（`build_monthly_author_agent` /
  `build_class_monthly_author_agent` / `build_child_record_author_agent` /
  `build_nursery_record_author_agent` / `build_review_agent` / `build_improver_agent` /
  `build_proofreader_agent`（校正AI） / `build_upload_parser_agent`（取込抽出AI） /
  `build_monthly_pipeline` / `build_class_monthly_pipeline` /
  `build_child_record_pipeline` / `build_nursery_record_pipeline` / `build_root_agent`）。
  トップレベルでインスタンス化しない（例外は `agent.py` の `root_agent` のみ）。
  **保育日誌の AI 生成は退役**したため `build_author_agent` / `build_document_pipeline` は無い（日誌は手入力＝web）。
- エージェント間の受け渡しは **`output_key` → `state[...]`**（`state["draft"]` / `state["review"]`）。
  独自グローバルで渡さない。
- スキーマは `schemas/` の pydantic モデルに集約。同じ関心事を別所で二重定義しない。
- instruction（プロンプト）は各層の `prompts.py` に分離する。
- docstring・コメント・LLM プロンプトは日本語。

# 実装着手前の確認

[エージェント実装状況.md](エージェント実装状況.md) を必ず読み、対象の現状と制約を確認する。

# IMPORTANT: 個人情報・秘密の取り扱い

- **実データ（個人情報を含みうる保育書類・園データ）は絶対にコミットしない**。`data/`・`samples/private/`・
  `knowledge/保育所保育指針/*` は gitignore 済み。新たな実データ置き場は先に gitignore する。
- `.env`・サービスアカウント鍵（`*-key.json` 等）はコミットしない（gitignore 済み）。
- **生成書類・eval ケースに子ども・保護者の実名を書かない**（仮名・属性で表す＝架空の子のみ）。
  eval seed／月案 seed の子どもは現場の日誌に寄せた**実在しない仮名の固定ロスター**（下の名前＋ちゃん/くん）を使い、
  `tests/test_eval_cases.py` の allowlist で機械的に担保する（記号名「架空児A」には戻さない）。
- 補足: CLAUDE.md は強制でなく文脈。PII 非コミットを確実化するなら `PreToolUse` hook が本筋（将来 `.claude/` で）。

# ブランチ・コミット・PR

利用するエージェントのグローバル指示のブランチ戦略・コミット/PR 規約に従う（ここでは再定義しない）。

## Codex 固有の自動公開フロー

このプロジェクトでは、グローバル規約のうち「push・PR 作成はユーザー確認後」とする部分を意図的な例外として扱う。
ユーザーから変更実装を依頼された場合、作業ブランチ上で次を確認なしに自動実行してよい。

1. テスト・lint・必要な検証を実行する
2. 意味的なまとまりごとに日本語のコミットを作成する
3. 作業ブランチをリモートへ push する
4. PR を作成する（PR タイトル・本文は日本語。生成ツール由来の署名・宣伝行は付けない）

main への直接 push、main への merge、既存 PR の承認・merge は自動実行しない。PR 作成後は、URL と検証結果を報告して停止する。
未コミット変更、テスト失敗、認証不足、競合、または対象範囲が不明な場合は、無理に公開せず停止して状況を報告する。

## Codex 固有のマージ後の整理

ユーザーが PR を merge したことを報告した場合に限り、次の後処理を自動実行してよい。

1. リモートを fetch し、対象 PR と作業ブランチが実際に merge 済みであることを確認する
2. merge 済みの作業ブランチ、対応するローカル worktree、不要な remote-tracking ref を整理する
3. primary checkout の統合ブランチを更新する
4. `git status`、worktree 一覧、残存ブランチを確認し、結果を報告する

ただし、未コミット変更、未 push のコミット、未 merge、同名ブランチの別用途、または削除対象を安全に特定できない状態では、ブランチや worktree を削除しない。削除せずに状況を報告して判断を仰ぐ。
