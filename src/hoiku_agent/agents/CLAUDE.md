# agents/ ＝ agentic「中身の決定」層（責務②）

ここで Claude がすること：各欄に**何を書くか**・不足をどう補うかを LlmAgent に判断させる
（情報収集・質問生成・「姿→ねらい/評価」の変換＝勘所）。設計コンテキスト §6（作成AI）/ §7（レビューAI）。

## 守る制約

- **author は単一 LlmAgent（内部を多層化しない）。** `gather → act → verify` は instruction＋ツール呼び出し
  ループで表現し、収集・質問生成・起案を別エージェントに分けない（§4/§6）。**ただし巡回（レビュー差し戻しでの
  再作成）は harness が担う**：`harness/pipeline.py` の `build_authoring_loop` が [作成 → レビュー →
  ApprovalGate] を1巡とする LoopAgent に author を包み、NEEDS_REVISION のとき次巡で author が指摘点を直して
  再提出する（「巡回保証が要る」と判断したための設計＝旧 v0 は author をループに包まなかった）。再作成時の
  挙動（白紙から作り直さない・同じ不足で `ask_caregiver` を繰り返さない）は `prompts.py` の revision mode。
  **月案・児童票も同じ形**（`monthly_author_agent.py` / `child_record_author_agent.py`＝単一 LlmAgent・
  authoring_loop を日誌と共用）。違いは instruction（月案/児童票スキーマ。児童票は**開示前提の肯定的・非断定的
  表現**を含む＝§19）と、前段 `DigestPrepAgent` が決定的集計した集積（月案＝前月 L2／児童票＝期間 L3）を読み
  要約する点（§10/§19）。
- **reviewer は Evaluator** で別視点の点検に徹する（日誌/月案/児童票共用・開示前提の表現観点を含む）。**巡回（LoopAgent）と APPROVED 早期終了の
  "制御" は harness/pipeline.py 側**（決定的）。ここは reviewer 単体（指摘の生成）を返す。`date` 等 harness が
  確定時に補完する機械的メタの欠落は指摘対象外＝内容点検に集中する（prompts.py の注意書き）。
- **factory で返す。** `build_author_agent` / `build_monthly_author_agent` / `build_child_record_author_agent` /
  `build_review_agent`。
  トップレベルでインスタンス化しない（例外は `agent.py` の root_agent のみ）。任意引数 `model`（既定
  None＝`models.build_model()`＝`gemini_model` を `model_location`＝global に固定した Gemini。Gemini 3.x は
  Vertex global 専用で RAG/Memory のリージョンと分離するため＝§11/`models.py`）は決定論E2E で `FakeLlm` 等の
  `BaseLlm` を差し込むための注入口。本番は引数なしで不変。
- **受け渡しは output_key→state**（`state["draft"]` / `state["review"]`）。独自グローバルで渡さない。
- **文書作成指針は agent が読みに行かない**（`read_policy` ツールは撤去）。`instructions.py` の InstructionProvider
  （`build_author_instruction`／`build_review_instruction`）が author/reviewer の `instruction` を callable にし、
  作る書類（doc_type）の scope で harness の `render_for_doc`（共通＋当該書類の勘所）＋集積（前月/期間・state の
  digest を `format_digest_for_prompt`）を **prompt 冒頭へ前置注入**する（author は factory で scope 固定／reviewer は
  共用のため state["doc_type"]→scope 解決）。指針を agent の**与件**にする＝探索を LLM に委ねず決定的に用意（§5）。
  ここは prompt 文字列の**組み立て**だけで、指針テキストの再生・集積の整形という決定ロジック実体は harness に置く
  （tools が harness を呼ぶ薄いラッパなのと同じ）。prompts.py の各 instruction は「この指示の冒頭に示した指針/集積」を参照する。
- **instruction は `prompts.py` に分離**（ADK 慣習）。日本語で書く。

## 決定的処理を書きたくなったら

それは harness/ の責務。`../harness/` に実体を置き、`../tools/` の薄いラッパ経由で呼ぶ
（ここに必須欄チェックや整形ロジックを再実装しない）。
