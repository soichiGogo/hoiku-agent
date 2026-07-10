---
name: e2e
description: 決定論E2E（結合テスト）を回す／網羅を点検する。FakeLlm 注入で author→review→finalize の全経路を LLM/GCP 非依存（creds不要・無料・決定的）に通し、結合テストで担保すべき制御フロー（連結・APPROVED早期終了・巡回上限・確定の成功/parse失敗/検証不足・HITL不発火）を検証する。harness/agents/prompts 変更後の回帰チェックに使う。
argument-hint: "[run | audit]"
allowed-tools: Bash, Read, Edit
---

# 決定論E2E（結合テスト）を回す／網羅を点検する

設計コンテキスト §4/§5/§16。**harness（型の保証）と agents（中身）の "結合"＝パイプラインの順序制御**を、
実 Gemini を呼ばずに検証する層。`author`/`reviewer` の `build_xxx(model=...)` に `FakeLlm`（`BaseLlm` の
決定的スタブ）を注入し、`document_pipeline` を実 ADK ランタイムで end-to-end に回す。実体は
`tests/test_e2e/test_pipeline_e2e.py`。

- **この層は creds 不要・無料・決定的**＝毎PR/毎編集で回せる。「型と順序」だけを見る。
- **中身の品質（指針整合/10の姿/保護者向け表現）は採点しない**。それは層B eval＝`/adk-eval`（要 LLM・課金）。
- ブラウザ（agent-browser）は使わない（自作Web UIは無く、`adk web` は dev UI＝実LLMが走る別物）。

## 手順

1. **実行（引数 `run` または既定）**：`uv run --extra dev pytest -q tests/test_e2e/` を回す。
   - 失敗したら **根本原因を直す**。assertion を削除/skip/xfail/緩和して緑にしない（対症療法禁止＝AGENTS.md）。
   - pytest 出力を証拠として示す。`google-adk` 未導入環境では skip に降格する（想定どおり）。
2. **点検（引数 `audit`）**：結合テストで担保すべき制御フロー経路が網羅されているか照合する。
   harness が分岐を持つ点＝必須カバー（`harness/pipeline.py`・`harness/finalize.py`）:
   - **連結**：author→`state["draft"]`→reviewer→`state["review"]`→finalize→`state["final_document"]`
   - **早期終了**：reviewer 1行目 `APPROVED` で `ApprovalGate` が escalate（`is_approved`）
   - **巡回上限**：`APPROVED` が出ない場合 `MAX_REVIEW_ITERATIONS` で頭打ち→finalize へ抜ける
   - **確定3経路**：① 成功（`validation` 空・`final_document` 生成）② parse 失敗（`finalize_parse_error`）
     ③ 検証不足（`validation` 非空でも確定下書きは生成される）
   - **HITL 関門**：`ask_caregiver` を発火させずに通る／確定段で `awaiting_caregiver_approval=True`
   - **ルータ分岐と集積還流**：doc_type 未設定＝日誌（既定）／"月案"＝L2 還流（`test_monthly_e2e.py`）／
     "保育経過記録"＝L3 還流（`test_child_record_e2e.py`）。prep の集計→digest→確定と、seed 無しの降格も見る。
   - 不足経路があれば、それを **`FakeLlm` でスクリプト**した新規ケースを `tests/test_e2e/` に提案・追加する。
3. **月案・保育経過記録パスは配線済み＝本E2Eの対象**（§3/§19）。新しい doc_type を足したら対応 E2E も同時に足す
   （`docs/architecture.md` の実装状況と同期）。

注：このスキルは決定論層（無料・LLM非依存）専用。品質回帰は `/adk-eval`、ローカル実起動は `/run-pipeline`。
