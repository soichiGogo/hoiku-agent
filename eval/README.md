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
  `rubric_based_final_response_quality_v1` に rubric として配線。judge は3回採点の多数決。
- `gate_policy.json` … 軸別・ケース別の絶対品質 floor（3軸各0.8、各ケース2/3）と
  main比の非劣化マージン0.05。決定的な判定設定。
- `run_gate.py` … 採点→集計→ゲート判定の実体（`aggregate_rubric_scores`/`decide_gate`・判定式の SSOT）。
- `baseline.json` … main の eval 平均（committed）。`run_gate` が既定で読み PR の非劣化比較に使う。
  PR CIはPR内の値でなくbase SHAから抽出したbaselineを使い、候補側の基準改変を防ぐ。nightlyは自動更新しない。
  初回導入時にbaseの`mean`が明示的に`null`なら、候補baselineとそのCIの実採点値（平均・軸別平均・must_fix・
  ケース数・gate policy）が完全一致した場合だけ一度限りbootstrapする。baseが採点済みになれば候補値は無視する。
  変更時は `--update-baseline` で完全採点し、通常PRでレビューする。
- 実行は `uv run --extra eval python eval/run_gate.py`（ローカル採点）／`… --strict --output <path>`
  （CI＝採点不能も非0終了＋ケース別証跡）／`… --update-baseline`（意図的なbaseline更新）。
  いずれも要 `google-adk[eval]` ＋ LLM 資格情報。詳細規約は `CLAUDE.md`。
- `results/` … ローカル/Actionsの実行証跡（gitignore・Actions artifact。コミットしない）。
- `tests/test_eval.py` を直接使う場合も、暗黙の課金を防ぐため `RUN_LIVE_EVAL=1` を明示する。

## 評価ゲート

緑（auto-merge 可）の条件＝**全ケース×全rubricのcoverage 100%、軸/ケースfloor達成、PR平均がmain比の
非劣化マージン0.05以内、かつ `must_fix` 違反0**。9ケース×3軸では1セル差≈0.037だけをjudge揺れとして
許容し、2セル差≈0.074は赤にする。採点不能・rubric欠落・baseline未確立はCIで赤。baselineは自動追随
させずレビュー対象にする。**保育士OK ≠ マージOK**（採否はゲートが決める）。

## 「閉じる1事例」（提出前の必達点）

保育士の1要望を 捕捉→指針更新（競合なら保育士判断）→ゲート通過→デプロイ→還元 まで自走で1周通す。
競合解消の1シナリオを作り込む（大規模ルールの自動競合検出・多保育士の調停はスコープ外＝§8）。
