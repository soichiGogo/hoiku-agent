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
  前段 prep が決定的集計した集積（**依存モデル 2026-07**＝個別月案:前月 L2／保育経過記録:期間 L3＋**前回までの
  自己履歴すべて**／クラス月案:**クラス児童の保育経過記録すべて＋それまでのクラス月案すべて＋経過記録に未反映の
  期間の日誌**／要録:**それまでの保育経過記録すべて** L4）を InstructionProvider が **digest spec 列**で順に
  前置注入する点（クラス月案の指針 scope は個別月案と同じ「月案」を流用＝§10/§18/§19）。
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
- **校正AI（`proofreader_agent.py`＝`build_proofreader_agent`）も別エントリの単一 LlmAgent**（root_agent に載せない・
  upload_parser/improver と同型）。保育日誌の手入力後、「日本語をチェック」（`web/proofread`）から起こし、保育士が
  手入力した叙述文へ**校正の提案**（誤り・不自然さ・言い換え・開示前提の表現）を返す＝**AI は著者でなく校正者**
  （ヒアリング 2026-07）。tools なし・巡回なし・1パス。**提案のみ**（採否は保育士・自動書換しない）・**事実は変えない**
  （数値/仮名/日付/タグは触らない）・表記の機械的統一（子供→子ども）は finalize の notation が別途担う＝校正AI は notation で
  機械化できない観点に集中（役割分担・§5）。```json フェンス出力（web が復元し id→entry のパスへ写像）。開示前提の観点は
  kind で出し分け（保育経過記録/要録・§19）＝doc_type 非依存に設計（diary 先行）。
- **factory で返す。** `build_monthly_author_agent` / `build_class_monthly_author_agent` /
  `build_child_record_author_agent` / `build_nursery_record_author_agent` / `build_review_agent` /
  `build_upload_parser_agent` / `build_proofreader_agent`（**保育日誌の作成AI＝旧 `build_author_agent` は退役**＝日誌は手入力・ヒアリング 2026-07）。
  トップレベルでインスタンス化しない（例外は `agent.py` の root_agent のみ）。任意引数 `model`（既定
  None＝`models.build_model()`＝`gemini_model` を `model_location`＝global に固定した Gemini。Gemini 3.x は
  Vertex global 専用で RAG/Memory のリージョンと分離するため＝§11/`models.py`）は決定論E2E で `FakeLlm` 等の
  `BaseLlm` を差し込むための注入口。本番は引数なしで不変。
- **受け渡しは output_key→state**（`state["draft"]` / `state["review"]`）。独自グローバルで渡さない。
- `instructions.py` の InstructionProvider は作る書類の scope に応じた guideline と reference_policy の
  有効 source を提示する。参照本文は固定注入せず、author/reviewer が `fetch_reference(source)` で選択取得する。
  reviewer には reference_manifest も提示し、取得実績を検証できる（§5）。
  ここは prompt 文字列の**組み立て**だけで、指針テキストの再生・集積の整形という決定ロジック実体は harness に置く
  （tools が harness を呼ぶ薄いラッパなのと同じ）。prompts.py の各 instruction は「この指示の冒頭に示した指針/集積」を参照する。
- **instruction は `prompts.py` に分離**（ADK 慣習）。日本語で書く。

## 決定的処理を書きたくなったら

それは harness/ の責務。`../harness/` に実体を置き、`../tools/` の薄いラッパ経由で呼ぶ
（ここに必須欄チェックや整形ロジックを再実装しない）。
