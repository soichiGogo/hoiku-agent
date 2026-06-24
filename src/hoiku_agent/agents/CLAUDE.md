# agents/ ＝ agentic「中身の決定」層（責務②）

ここで Claude がすること：各欄に**何を書くか**・不足をどう補うかを LlmAgent に判断させる
（情報収集・質問生成・「姿→ねらい/評価」の変換＝勘所）。設計コンテキスト §6（作成AI）/ §7（レビューAI）。

## 守る制約（v0 の意図的な形）

- **author は単一 LlmAgent。** `gather → act → verify` は instruction＋ツール呼び出しループで表現し、
  **v0 では LoopAgent に包まない・多層マルチエージェント化しない**（§4/§6）。「巡回保証が要る」と
  分かるまで包まない（包むなら validate_fields OK を early-exit にする選択肢＝§6 補足）。
- **reviewer は Evaluator** で別視点の点検に徹する。**巡回（LoopAgent）と APPROVED 早期終了の
  "制御" は harness/pipeline.py 側**（決定的）。ここは reviewer 単体（指摘の生成）を返す。
- **factory で返す。** `build_author_agent` / `build_review_agent`。トップレベルでインスタンス化
  しない（例外は `agent.py` の root_agent のみ）。
- **受け渡しは output_key→state**（`state["draft"]` / `state["review"]`）。独自グローバルで渡さない。
- **instruction は `prompts.py` に分離**（ADK 慣習）。日本語で書く。

## 決定的処理を書きたくなったら

それは harness/ の責務。`../harness/` に実体を置き、`../tools/` の薄いラッパ経由で呼ぶ
（ここに必須欄チェックや整形ロジックを再実装しない）。
