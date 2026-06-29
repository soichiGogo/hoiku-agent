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
  **月案も同じ形**（`monthly_author_agent.py`＝単一 LlmAgent・authoring_loop を日誌と共用）。違いは instruction
  （月案スキーマ）と、前段 `MonthlyPrepAgent` が決定的集計した前月集積（L2 還流）を読み要約する点（§10）。
- **reviewer は Evaluator** で別視点の点検に徹する（日誌/月案共用）。**巡回（LoopAgent）と APPROVED 早期終了の
  "制御" は harness/pipeline.py 側**（決定的）。ここは reviewer 単体（指摘の生成）を返す。`date` 等 harness が
  確定時に補完する機械的メタの欠落は指摘対象外＝内容点検に集中する（prompts.py の注意書き）。
- **factory で返す。** `build_author_agent` / `build_monthly_author_agent` / `build_review_agent`。
  トップレベルでインスタンス化しない（例外は `agent.py` の root_agent のみ）。任意引数 `model`（既定
  None＝`models.build_model()`＝`gemini_model` を `model_location`＝global に固定した Gemini。Gemini 3.x は
  Vertex global 専用で RAG/Memory のリージョンと分離するため＝§11/`models.py`）は決定論E2E で `FakeLlm` 等の
  `BaseLlm` を差し込むための注入口。本番は引数なしで不変。
- **受け渡しは output_key→state**（`state["draft"]` / `state["review"]`）。独自グローバルで渡さない。
- **instruction は `prompts.py` に分離**（ADK 慣習）。日本語で書く。

## 決定的処理を書きたくなったら

それは harness/ の責務。`../harness/` に実体を置き、`../tools/` の薄いラッパ経由で呼ぶ
（ここに必須欄チェックや整形ロジックを再実装しない）。
