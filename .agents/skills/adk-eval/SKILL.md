---
name: adk-eval
description: 層B の評価ゲートを回す。eval/cases/*.evalset.json を ADK evaluation で採点し、3軸（指針整合/10の姿/保護者向け表現）平均と must_fix 違反を集計してゲート判定（main比 非劣化 & must_fix 0）を報告する。指針/プロンプト/モデル変更後の回帰チェックに使う。
argument-hint: "[evalset名 または all]"
---

# 評価ゲートを回す（層B・回帰チェック）

設計コンテキスト §12。prompt/tool/モデル/指針の変更がスコアを下げていないかを検証する。

## 手順

1. 対象を決める（引数 $ARGUMENTS。未指定 or `all` なら `eval/cases/*.evalset.json` すべて）。
   ケースが無ければ「未整備」と報告して終了（架空児データのみ・PII禁止＝§14）。
2. `adk eval src/hoiku_agent eval/cases/<name>.evalset.json`（複数可）を実行する。
   ※ `adk eval` の正確な引数・evalset JSON 構造は公式 docs で要確認（未決＝§18）。
   CI 統合なら代わりに `pytest tests/test_eval.py`。
3. 各ケースを 3軸 LLM-judge（`eval/judges/` の3プロンプト）で 0–1 採点し、3軸平均をケーススコアにする。
4. ゲート判定を報告する: **PR の eval 平均が main 比で低下なし、かつ must_fix 違反0 → 緑（auto-merge可）**。
   赤なら却下理由（どのケース・どの軸・どの must_fix）を具体的に示す。**保育士OK ≠ マージOK**。

注: judge も Gemini 呼び出しを伴う。閾値は 15ケース貯まってから軸別に調整する（v0 は main 平均非劣化のみ）。
