# eval（「回す」層B：改善サイクルの評価）

設計コンテキスト §8（改善エージェント）/ §12（DevOps・eval）に対応。

保育士の **👍👎・修正差分** を評価ケースに還元し、prompt / tool / モデル / 指針の改善が
回帰していないかを PR ゲートで検証する。スコア推移が「回した証拠」になる。

## 構成

- `cases/` … 評価ケース（ADK evalset JSON `*.evalset.json`）。1ケース＝入力（観察メモ＋DocumentSpec）と
  期待値（採点の根拠／`must_fix` 条件）。**15–30ケースで十分**（数より質）。**実データ（PII）禁止＝架空児のみ**。
- `judges/` … LLM-as-judge プロンプト。**3軸**：①指針整合（保育所保育指針）②10の姿マッピング
  ③保護者向け表現の適切さ。各軸 0–1 で採点し3軸平均をケーススコアにする。
- `test_config.json` … 3軸（`axis_*`）＋must_fix（`mustfix_*`）を ADK の
  `rubric_based_final_response_quality_v1` に rubric として配線。
- `run_gate.py` … 採点→集計→ゲート判定の実体（`aggregate_rubric_scores`/`decide_gate`・判定式の SSOT）。
- `baseline.json` … main の eval 平均（committed）。`run_gate` が既定で読み PR の非劣化比較に使う。nightly が
  `--update-baseline` で更新・コミットバックする（不在/未採点は比較なしへ降格）。手で編集しない。
- 実行は `uv run --extra eval python eval/run_gate.py`（採点して判定）／`… --update-baseline`（baseline 更新）。
  いずれも要 `google-adk[eval]` ＋ LLM 資格情報。詳細規約は `CLAUDE.md`。

## 評価ゲート

緑（auto-merge 可）の条件＝**PR の eval 平均が main 比で低下なし、かつ `must_fix` 違反0**。
main 比の基準は committed `baseline.json`（nightly が更新）。v0 は「main 平均を下回らない」のみをゲートにし、
軸別閾値は 15ケース貯まってから調整する。**保育士OK ≠ マージOK**（採否はゲートが決める）。

## 「閉じる1事例」（提出前の必達点）

保育士の1要望を 捕捉→指針更新（競合なら保育士判断）→ゲート通過→デプロイ→還元 まで自走で1周通す。
競合解消の1シナリオを作り込む（大規模ルールの自動競合検出・多保育士の調停はスコープ外＝§8）。
