# improver/ ＝ 二階「回す（まわす）」自走ループ（責務③）

ここで Claude がすること：保育士の修正メモ・👍👎 から、育つ指針＝**構造化カードストア**
（置き場の解決は harness/policy_store＝`POLICY_STORE_URI` の GCS またはローカル `knowledge/文書作成指針.json`。
この層は置き場を知らない）の更新を**自走提案**し、既存カードとの**意味的競合**を精査、
競合があれば保育士に該当カードを提示して比較相談し、**保育士の決定で即反映**するループを組む。設計コンテキスト §8。

## 守る制約（最も副作用が大きい層）

- **root_agent とは別エントリ。** 一階の `agent.py`（root_agent＝document_pipeline）に組み込まない・
  `improver` を import しない。**自動起動しない**（手動トリガ：専用スクリプト or Web の SSE 駆動）。
- **番人＝意味的競合精査＋保育士の決定で即反映。** 4ツールで回す：`read_policy_cards`（既存カードを読む）→
  `propose_policy_card`（追加/改訂案＋意味的競合の申告。完全重複は安全網が検出）→ 競合なら `ask_caregiver`
  で**該当カードと新案を比較相談**（無くても反映可否を確認）→ `commit_policy_card`（保育士の決定で
  **即反映**＝add／supersede→`policy_store.save_book`）。**評価ゲート（eval）は取り込みフローから外す**
  （eval は CI の品質回帰として別系統で温存＝decouple）。**保育士の決定＝確定**（保育士OK≠マージOK は撤回）。
- **指針の編集の決定的実体は harness/policy_store**（CRUD/render/完全重複ガード/履歴）。「回した証拠」＝
  カード内蔵の変更履歴（decided_by 含む）。ここで subprocess・採点・JSON 編集を再実装しない。
- **意味的競合の判定はこのエージェント（LLM）の責務**。harness は完全重複の安全網のみ（決定的）。
- **単一 LlmAgent＋少数ツール**（多層化しない＝§4）。factory `build_improver_agent` で返す。
- v0 スコープ：add／supersede（置換）。「閉じる1事例」を提出前に必達（捕捉→精査→提案→比較相談→即反映 を1周）。
  大規模ルールの自動競合検出・多保育士調停はスコープ外。
