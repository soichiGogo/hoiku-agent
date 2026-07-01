# eval/ ＝ 層B「回す」評価ゲート

ここで Claude がすること：保育士の修正差分・👍👎 を評価ケース化し、prompt/tool/モデル/指針の変更が
**回帰していないか**を PR ゲートで検証する。スコア推移が「回した証拠」。設計コンテキスト §8/§12。

## 規約（このディレクトリ限定・非自明）

- **評価セットは `cases/` に ADK の evalset JSON（`*.evalset.json`）で置く。** 1ケース＝入力（観察メモ
  ＋DocumentSpec）と期待値（採点の根拠／`must_fix` 条件）。**15–30ケースで十分（数より質＝現場のリアルな失敗）。**
- **judge プロンプトは `judges/` に置く。3軸固定（勝手に増減しない）**：
  ①指針整合（保育所保育指針への整合）②10の姿マッピング ③保護者向け表現の適切さ。
  各軸 LLM-judge を **0–1** で採点し、3軸平均をケーススコアとする。
  （「文書作成指針への準拠」を4軸目にするかは設計余地だが原典に無い追加なので v0 は3軸）。
- **judge の配線は `test_config.json`**：ADK ネイティブの `rubric_based_final_response_quality_v1` に
  3軸（`axis_*`）と must_fix（`mustfix_*`）を rubric として載せる。`judges/*.md` は rubric 文面（text_property）の
  出所・全文。**rubric_id 体系（axis_* / mustfix_*）と判定式の実体は `run_gate.py`** に1つ（二重実装しない）。
- **PR ゲート＝AI版回帰テスト**：緑（auto-merge 可）の条件は **PR の eval 平均が main 比で低下なし、かつ
  `must_fix` 違反0**。v0 は「main 平均を下回らない」のみをゲートにし、軸別閾値は 15ケース貯まってから調整。
  判定は `run_gate.py`：rubric 採点 → `aggregate_rubric_scores`（axis 平均＝ケーススコア／mustfix の no＝違反）
  → `decide_gate`（main 比 非劣化 かつ must_fix 0）。採点不能（creds/ケース/依存なし）は `passed=None` で降格。
- **main 比の基準は committed `eval/baseline.json`**：`run_gate` が既定で `load_baseline` して読む。nightly/手動の
  main eval-gate が `--update-baseline` で採点し直して更新・コミットバックし、PR はこれと比べる（`load_baseline`/
  `build_baseline_record`/`write_baseline`・実体は `run_gate.py`）。不在/未採点（mean=null）/壊れは比較なしへ降格＝偽の赤を出さない。
- **実行**：`uv run --extra eval python eval/run_gate.py`（採点して判定）／`… --update-baseline`（main を採点して
  baseline.json 更新）。いずれも要 `--extra eval` ＝ `google-adk[eval]` ＋ LLM 資格情報 /
  または `pytest tests/test_eval.py`（CI 統合・creds 無は skip）/ 判定式の単体は `tests/test_eval_gate.py`（LLM 非依存）。
  **このゲートは CI の品質回帰テスト専用**（prompt/モデル/指針の変更を守る）。**改善エージェント（improver）の
  指針取り込みには関与しない**＝v1 で decouple（取り込みの番人は「意味的競合精査＋保育士の決定で即反映」＝§8）。

## IMPORTANT: PII を入れない

`cases/` に実データ（個人情報）を入れない。**架空の子のみ**・子ども/保護者は仮名・属性で表す（§14）。
子どもの名前は現場の日誌の書き方に寄せた**実在しない仮名の固定ロスター**（下の名前＋ちゃん/くん）を使い、
`tests/test_eval_cases.py` の `_FICTIONAL_ROSTER` allowlist で「ロスター外＝実名/未知名」を機械的に落とす。
新しい架空の子を足すときは、実在し得ない仮名をロスターに追加してから使う（「架空児A」のような記号名には戻さない）。
