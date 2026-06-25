"""eval ゲートの決定ロジック（純関数・§12）の単体テスト（LLM 非依存・高速）。

設計コンテキスト §12/§16：ゲートの判定式（軸平均→main 比 非劣化＋must_fix 0）は決定的ロジックなので
pytest で必須。ADK の採点（要 creds）から切り離した純関数として検証し、「偽の緑を出さない」を担保する。
ADK 駆動部（_score_cases_with_adk）は要 creds のためここでは回さない（tests/test_eval.py が降格を見る）。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

_REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_run_gate():
    gate_path = _REPO_ROOT / "eval" / "run_gate.py"
    spec = importlib.util.spec_from_file_location("hoiku_eval_run_gate", gate_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gate = _load_run_gate()


# ──────────────────────── aggregate_rubric_scores ────────────────────────


def _all_pass() -> dict:
    return {rid: 1.0 for rid in gate.AXIS_RUBRIC_IDS + gate.MUST_FIX_RUBRIC_IDS}


def test_aggregate_all_pass_gives_mean_one_no_violation():
    agg = gate.aggregate_rubric_scores([_all_pass(), _all_pass()])
    assert agg["mean"] == 1.0
    assert agg["must_fix_violations"] == 0
    assert agg["n_scored"] == 2
    assert all(v == 1.0 for v in agg["axis_means"].values())


def test_case_score_is_mean_of_axis_rubrics():
    # 3軸が 1,1,0 → ケーススコア＝2/3
    scores = {**_all_pass()}
    scores[gate.AXIS_RUBRIC_IDS[2]] = 0.0
    agg = gate.aggregate_rubric_scores([scores])
    assert abs(agg["mean"] - 2 / 3) < 1e-9


def test_must_fix_no_counts_as_violation():
    scores = {**_all_pass()}
    scores[gate.MUST_FIX_RUBRIC_IDS[0]] = 0.0  # 実名あり等＝must_fix 違反
    agg = gate.aggregate_rubric_scores([scores])
    assert agg["must_fix_violations"] == 1
    # must_fix の不充足は軸平均（ケーススコア）には混ぜない（軸は3つ固定）
    assert agg["mean"] == 1.0


def test_missing_rubric_ids_are_ignored_not_zeroed():
    # judge が一部 rubric を返さなくても、欠落を 0 と誤認しない（present のみ平均）
    agg = gate.aggregate_rubric_scores([{gate.AXIS_RUBRIC_IDS[0]: 1.0}])
    assert agg["mean"] == 1.0
    assert agg["must_fix_violations"] == 0


def test_empty_scores_give_none_mean():
    agg = gate.aggregate_rubric_scores([{}, {}])
    assert agg["mean"] is None
    assert agg["n_scored"] == 0


# ──────────────────────── decide_gate ────────────────────────


def test_decide_none_when_unscored():
    assert gate.decide_gate(None, 0.8, 0) is None


def test_decide_red_on_must_fix_violation():
    assert gate.decide_gate(0.95, 0.5, 1) is False


def test_decide_green_when_no_baseline_and_no_violation():
    assert gate.decide_gate(0.7, None, 0) is True


def test_decide_green_on_non_regression():
    assert gate.decide_gate(0.80, 0.80, 0) is True  # 同点は非劣化＝緑
    assert gate.decide_gate(0.81, 0.80, 0) is True


def test_decide_red_on_regression():
    assert gate.decide_gate(0.79, 0.80, 0) is False


# ──────────────────────── extract_rubric_scores ────────────────────────


def _case_result(rubric_scores: dict[str, float], metric_name: str | None = None):
    """ADK の EvalCaseResult を duck-typing で模す（getattr で読むため SimpleNamespace で足りる）。"""
    name = metric_name if metric_name is not None else gate.RUBRIC_METRIC
    details = SimpleNamespace(
        rubric_scores=[SimpleNamespace(rubric_id=k, score=v) for k, v in rubric_scores.items()]
    )
    metric_result = SimpleNamespace(metric_name=name, details=details)
    return SimpleNamespace(overall_eval_metric_results=[metric_result])


def test_extract_reads_rubric_scores_from_case_result():
    scores = gate.extract_rubric_scores(_case_result({"axis_expression": 1.0, "mustfix_x": 0.0}))
    assert scores == {"axis_expression": 1.0, "mustfix_x": 0.0}


def test_extract_ignores_other_metrics():
    assert gate.extract_rubric_scores(_case_result({"a": 1.0}, metric_name="other_metric")) == {}


def test_extract_robust_to_missing_shape():
    assert gate.extract_rubric_scores(SimpleNamespace()) == {}
    assert gate.extract_rubric_scores(SimpleNamespace(overall_eval_metric_results=None)) == {}


# ──────────────────────── 統合：no_cases 降格 ────────────────────────


def test_run_gate_no_cases_degrades(tmp_path):
    result = gate.run_gate(cases_dir=tmp_path)  # 空ディレクトリ＝ケースなし
    assert result["status"] == "no_cases"
    assert result["passed"] is None
