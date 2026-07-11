# eval/ ＝ 層B「回す」評価ゲート

ここで Claude がすること：保育士の修正差分・👍👎 を評価ケース化し、prompt/tool/モデル/指針の変更が
**回帰していないか**を PR ゲートで検証する。スコア推移が「回した証拠」。設計コンテキスト §8/§12。

## 規約（このディレクトリ限定・非自明）

- **評価セットは `cases/` に ADK の evalset JSON（`*.evalset.json`）で置く。** 1ケース＝入力（観察メモ
  ＋DocumentSpec）と期待値（採点の根拠／`must_fix` 条件）。**15–30ケースで十分（数より質＝現場のリアルな失敗）。**
  保育経過記録（`child_record.*`）は `session_input.state` で doc_type/期間日誌を seed する（L3 還流＝§19）。
  参照ドラフトの型検査は `tests/test_eval_cases.py` がファイル名で保育経過記録/保育要録を分岐する（日誌 evalset は手入力化で撤去）。
- **judge プロンプトは `judges/` に置く。3軸固定（勝手に増減しない）**：
  ①指針整合（保育所保育指針への整合）②10の姿マッピング ③保護者向け表現の適切さ。
  各軸 LLM-judge を **0–1** で採点し、3軸平均をケーススコアとする。
  （「文書作成指針への準拠」を4軸目にするかは設計余地だが原典に無い追加なので v0 は3軸）。
- **judge の配線は `test_config.json`**：ADK ネイティブの `rubric_based_final_response_quality_v1` に
  3軸（`axis_*`）と must_fix（`mustfix_*`）を rubric として載せる。`judges/*.md` は rubric 文面（text_property）の
  出所・全文。judge は3回採点の多数決（ADK既定5回に対するコスト折衷）。**rubric_id 体系
  （axis_* / mustfix_*）と判定式の実体は `run_gate.py`** に1つ（二重実装しない）。
  ADK 2.3の複数行Rationale parser欠落は、`run_gate` の専用metric registryへID marker対応parserを注入して吸収する。
- **PR ゲート＝AI版回帰テスト**：緑（auto-merge 可）の条件は **PR の eval 平均が main 比の非劣化マージン
  0.05以内、かつ
  `must_fix` 違反0**に加え、`gate_policy.json` の軸/ケースfloorと全ケース×全rubric coverage 100%を要求する。
  採点不能・rubric欠落・baseline未確立は `passed=None`、CIの `--strict` では非0終了（fail-closed）。
  9ケース×3軸の27セルでは1セル差≈0.037だけをjudge揺れとして許容し、2セル差≈0.074は赤にする。
- **main 比の基準は committed `eval/baseline.json`**：`run_gate` が既定で読む。nightly は監視だけで自動更新しない。
  `--update-baseline` はcoverage 100%・floor達成・must_fix 0のときだけ書き、通常PRでレビューする。
- **実行**：`uv run --extra eval python eval/run_gate.py`（ローカル）／`… --strict --output <path>`（CI）／
  `… --update-baseline`（意図的なbaseline更新）。要 `google-adk[eval]`＋LLM資格情報。純関数の判定テストは
  `tests/test_eval_gate.py`。`tests/test_eval.py` は `RUN_LIVE_EVAL=1` 明示時だけ実行（暗黙課金防止）。
  CIゲート本体はstrict CLIを直接呼ぶ。
  **このゲートは CI の品質回帰テスト専用**（prompt/モデル/指針の変更を守る）。**改善エージェント（improver）の
  指針取り込みには関与しない**＝v1 で decouple（取り込みの番人は「意味的競合精査＋保育士の決定で即反映」＝§8）。

## IMPORTANT: PII を入れない

`cases/` に実データ（個人情報）を入れない。**架空の子のみ**・子ども/保護者は仮名・属性で表す（§14）。
子どもの名前は現場の日誌の書き方に寄せた**実在しない仮名の固定ロスター**（下の名前＋ちゃん/くん）を使い、
`tests/test_eval_cases.py` の `_FICTIONAL_ROSTER` allowlist で「ロスター外＝実名/未知名」を機械的に落とす。
新しい架空の子を足すときは、実在し得ない仮名をロスターに追加してから使う（「架空児A」のような記号名には戻さない）。
