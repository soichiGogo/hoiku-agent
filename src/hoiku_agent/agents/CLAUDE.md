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
  **個別月案・クラス月案・保育経過記録・保育要録も同じ形**（`monthly_author_agent.py` /
  `class_monthly_author_agent.py` / `child_record_author_agent.py` / `nursery_record_author_agent.py`＝
  単一 LlmAgent・authoring_loop を日誌と共用）。違いは instruction（月案/クラス月案/保育経過記録/要録スキーマ。
  **クラス月案は園の実様式**＝クラス全体のねらい・区分×領域グリッド〔養護2本柱＋教育5領域・0–2/3–5 共通〕・
  0–2 は登場児ぶんの個人目標を生成し、評価系欄は AI 非生成＝§18。保育経過記録・要録は**開示前提の肯定的・非断定的表現**を
  含む＝§19。要録は小学校引継ぎ＝10の姿の活用・最終年度に至るまでの育ちを recall_child_history から叙述）と、
  前段 prep が決定的集計した集積（個別/クラス月案＝前月 L2／保育経過記録＝期間 L3／要録＝**最終年度の保育経過記録** L4＝
  `RecordDigestPrepAgent`・formatter は `format_record_digest_for_prompt`）を InstructionProvider が前置注入する点
  （クラス月案の指針 scope は個別月案と同じ「月案」を流用＝§10/§18/§19）。
- **reviewer は Evaluator** で別視点の点検に徹する（日誌/月案/保育経過記録/保育要録共用・開示前提の表現観点を含む）。**巡回（LoopAgent）と APPROVED 早期終了の
  "制御" は harness/pipeline.py 側**（決定的）。ここは reviewer 単体（指摘の生成）を返す。`date` 等 harness が
  確定時に補完する機械的メタの欠落は指摘対象外＝内容点検に集中する（prompts.py の注意書き）。
- **アップロード取込の抽出AI（`upload_parser_agent.py`＝`build_upload_parser_agent`）は別エントリの単一 LlmAgent**
  （improver と同じく root_agent には載せない）。「書類を見る」タブのアップロード（`web/upload_parse`）から起こし、
  既にある保育書類（スキャンPDF/Word/Excel）を既存スキーマへ**忠実に書き起こす**（作文しない・tools なし・巡回なし・
  1パス）。種別は保育士が選択済み＝1スキーマに固定（instruction を種別で切替＝`build_upload_extract_instruction`）。
  対象キー・age_band・child は与件（保育士入力）を prompt に前置し、システムが最終的に上書きする（LLM の取り違えを封じる）。
  **output_schema は使わず作成AI と同じ ```json フェンス出力**（タグ欄の union で responseSchema が不安定なため・harness の
  `extract_json_block`→`finalize_entry` で復元・検査・整形＝決定的実体は harness）。確認・修正は保育士が編集フォームで行う。
- **factory で返す。** `build_author_agent` / `build_monthly_author_agent` / `build_class_monthly_author_agent` /
  `build_child_record_author_agent` / `build_nursery_record_author_agent` / `build_review_agent` /
  `build_upload_parser_agent`。
  トップレベルでインスタンス化しない（例外は `agent.py` の root_agent のみ）。任意引数 `model`（既定
  None＝`models.build_model()`＝`gemini_model` を `model_location`＝global に固定した Gemini。Gemini 3.x は
  Vertex global 専用で RAG/Memory のリージョンと分離するため＝§11/`models.py`）は決定論E2E で `FakeLlm` 等の
  `BaseLlm` を差し込むための注入口。本番は引数なしで不変。
- **受け渡しは output_key→state**（`state["draft"]` / `state["review"]`）。独自グローバルで渡さない。
- **文書作成指針は agent が読みに行かない**（`read_policy` ツールは撤去）。`instructions.py` の InstructionProvider
  （`build_author_instruction`／`build_review_instruction`）が author/reviewer の `instruction` を callable にし、
  作る書類（doc_type）の scope で harness の `render_for_doc`（共通＋当該書類の勘所）＋集積（前月/期間・state の
  digest を `format_digest_for_prompt`／**要録 L4 は最終年度の保育経過記録集積なので `format_record_digest_for_prompt`
  を formatter に差し替え**）を **prompt 冒頭へ前置注入**する（author は factory で scope・formatter 固定／reviewer は
  共用のため state["doc_type"]→scope/formatter 解決）。指針を agent の**与件**にする＝探索を LLM に委ねず決定的に用意（§5）。
  ここは prompt 文字列の**組み立て**だけで、指針テキストの再生・集積の整形という決定ロジック実体は harness に置く
  （tools が harness を呼ぶ薄いラッパなのと同じ）。prompts.py の各 instruction は「この指示の冒頭に示した指針/集積」を参照する。
- **instruction は `prompts.py` に分離**（ADK 慣習）。日本語で書く。

## 決定的処理を書きたくなったら

それは harness/ の責務。`../harness/` に実体を置き、`../tools/` の薄いラッパ経由で呼ぶ
（ここに必須欄チェックや整形ロジックを再実装しない）。
