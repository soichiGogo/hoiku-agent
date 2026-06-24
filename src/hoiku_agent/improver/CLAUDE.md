# improver/ ＝ 二階「回す（まわす）」自走ループ（責務③）

ここで Claude がすること：保育士の修正差分・👍👎 から、育つ指針（`knowledge/文書作成指針.md`）の
更新を構造化編集で**自走提案**し、評価ゲートを通して取り込むループを組む。設計コンテキスト §8。

## 守る制約（最も副作用が大きい層）

- **root_agent とは別エントリ。** 一階の `agent.py`（root_agent＝document_pipeline）に組み込まない・
  `improver` を import しない。**自動起動しない**（v0 は手動トリガ：`adk run` でモジュール指定 or 専用
  スクリプト）。
- **指針の編集は必ず HITL＋評価ゲート経由。** `knowledge/文書作成指針.md` を直接書き換えない。
  `propose_policy_change`（構造化編集）→ 競合なら `ask_caregiver` で保育士が正を確定 → `open_pr` →
  CI 評価ゲート（main 比 非劣化 & must_fix 0）→ 緑のみ取り込み。**保育士OK ≠ マージOK**（§8/§12）。
- **git 操作は harness/git_ops 経由**（決定的実体は1つ）。ここで subprocess を直接叩かない。
- **単一 LlmAgent＋少数ツール**（多層化しない＝§4）。factory `build_improver_agent` で返す。
- v0 スコープ：手動起動・1見出しへの add のみ・競合検出は文字列一致レベル。「閉じる1事例」を提出前に
  必達（捕捉→更新→ゲート→デプロイ→還元 を1周）。大規模ルールの自動競合検出・多保育士調停はスコープ外。
