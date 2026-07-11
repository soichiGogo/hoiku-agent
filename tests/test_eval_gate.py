"""eval ゲートの決定ロジック（純関数・§12）の単体テスト（LLM 非依存・高速）。

設計コンテキスト §12/§16：ゲートの判定式（軸平均→main 比の許容幅内＋must_fix 0）は決定的ロジックなので
pytest で必須。ADK の採点（要 creds）から切り離した純関数として検証し、「偽の緑を出さない」を担保する。
ADK 駆動部（_score_cases_with_adk）は要 creds のためここでは回さない（tests/test_eval.py が降格を見る）。
"""

from __future__ import annotations

import importlib.util
import json
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


def test_decide_none_when_no_baseline_and_no_violation():
    assert gate.decide_gate(0.7, None, 0) is None


def test_decide_green_on_non_regression():
    assert gate.decide_gate(0.80, 0.80, 0) is True  # 同点は非劣化＝緑
    assert gate.decide_gate(0.81, 0.80, 0) is True


def test_decide_red_on_regression():
    assert gate.decide_gate(0.79, 0.80, 0) is False


def test_decide_allows_one_cell_judge_variance_but_rejects_two_cells():
    # 9ケース×3軸＝27セル。1セル差は1/27≈0.037、2セル差は2/27≈0.074。
    margin = 0.05
    assert gate.decide_gate(26 / 27, 1.0, 0, non_inferiority_margin=margin) is True
    assert gate.decide_gate(25 / 27, 1.0, 0, non_inferiority_margin=margin) is False


def test_decide_never_uses_margin_for_must_fix():
    assert gate.decide_gate(1.0, 1.0, 1, non_inferiority_margin=0.05) is False


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


def test_extract_rationales_for_artifact():
    result = _case_result({"axis_expression": 1.0})
    score = result.overall_eval_metric_results[0].details.rubric_scores[0]
    score.rationale = "観察と解釈が分かれている"
    assert gate.extract_rubric_rationales(result) == {"axis_expression": "観察と解釈が分かれている"}


# ──────────────────────── coverage / 品質 floor ────────────────────────


def _case_score(eval_id: str, scores: dict | None = None) -> dict:
    return {
        "eval_id": eval_id,
        "scores": scores if scores is not None else _all_pass(),
        "rationales": {},
    }


def test_coverage_requires_every_case_and_rubric():
    complete = gate.validate_score_coverage([_case_score("a"), _case_score("b")], ["a", "b"])
    assert complete["complete"] is True

    missing = _all_pass()
    missing.pop(gate.AXIS_RUBRIC_IDS[0])
    incomplete = gate.validate_score_coverage([_case_score("a", missing)], ["a", "b"])
    assert incomplete["complete"] is False
    assert incomplete["missing_cases"] == ["b"]
    assert incomplete["missing_rubrics"]["a"] == [gate.AXIS_RUBRIC_IDS[0]]


def test_coverage_rejects_duplicate_and_unexpected_cases():
    coverage = gate.validate_score_coverage(
        [_case_score("a"), _case_score("a"), _case_score("x")], ["a", "b"]
    )
    assert coverage["complete"] is False
    assert coverage["duplicate_cases"] == ["a"]
    assert coverage["unexpected_cases"] == ["x"]


def test_quality_floors_report_axis_and_case_failures():
    scores = _all_pass()
    scores[gate.AXIS_RUBRIC_IDS[0]] = 0.0
    cases = [_case_score("bad", scores), _case_score("good")]
    agg = gate.aggregate_rubric_scores([case["scores"] for case in cases])
    policy = {
        "axis_minimums": {rubric_id: 0.8 for rubric_id in gate.AXIS_RUBRIC_IDS},
        "case_minimum": 0.8,
    }
    result = gate.evaluate_quality_floors(cases, agg, policy)
    assert any("axis_guideline_alignment" in failure for failure in result["failures"])
    assert any("bad: case_mean" in failure for failure in result["failures"])
    assert result["case_means"]["bad"] == 2 / 3


def test_committed_gate_policy_and_judge_sampling_are_hardened():
    policy = gate.load_gate_policy()
    assert set(policy["axis_minimums"]) == set(gate.AXIS_RUBRIC_IDS)
    assert all(0 < value <= 1 for value in policy["axis_minimums"].values())
    assert policy["non_inferiority_margin"] == 0.05
    config = json.loads(gate._TEST_CONFIG.read_text(encoding="utf-8"))
    metric = config["criteria"][gate.RUBRIC_METRIC]
    assert metric["judge_model_options"]["num_samples"] >= 3
    for rubric in metric["rubrics"]:
        assert f"[{rubric['rubric_id']}]" in rubric["rubric_content"]["text_property"]


def test_multiline_autorater_parser_handles_adk_23_output_shape():
    response = """Property: [axis_expression] 保護者向け表現である。
Evidence:
- 観察した姿が書かれている。
Rationale:
観察事実と解釈が分かれている。
断定表現もない。
Verdict: yes

Property: [mustfix_no_definitive_eval] 断定評価がない。
Evidence: N/A
Rationale: 「できない」を中心にしていない。
Verdict: no
"""
    assert gate.parse_autorater_blocks(response) == [
        {
            "property": "[axis_expression] 保護者向け表現である。",
            "rationale": "観察事実と解釈が分かれている。\n断定表現もない。",
            "score": 1.0,
        },
        {
            "property": "[mustfix_no_definitive_eval] 断定評価がない。",
            "rationale": "「できない」を中心にしていない。",
            "score": 0.0,
        },
    ]


# ──────────────────────── 統合：no_cases 降格 ────────────────────────


def test_run_gate_no_cases_degrades(tmp_path):
    result = gate.run_gate(cases_dir=tmp_path)  # 空ディレクトリ＝ケースなし
    assert result["status"] == "no_cases"
    assert result["passed"] is None


# ──────────────────────── baseline（committed eval/baseline.json・§12） ────────────────────────


def test_load_baseline_missing_returns_none(tmp_path):
    assert gate.load_baseline(tmp_path / "nope.json") is None


def test_load_baseline_reads_mean(tmp_path):
    p = tmp_path / "baseline.json"
    p.write_text('{"mean": 0.73}', encoding="utf-8")
    assert gate.load_baseline(p) == 0.73


def test_load_baseline_null_mean_returns_none(tmp_path):
    # 未採点（初回）＝比較なしへ降格（偽の赤を出さない）
    p = tmp_path / "baseline.json"
    p.write_text('{"mean": null}', encoding="utf-8")
    assert gate.load_baseline(p) is None


def test_load_baseline_bool_mean_returns_none(tmp_path):
    # bool は int サブクラス。True を 1.0 と誤読しない
    p = tmp_path / "baseline.json"
    p.write_text('{"mean": true}', encoding="utf-8")
    assert gate.load_baseline(p) is None


def test_load_baseline_malformed_returns_none(tmp_path):
    p = tmp_path / "baseline.json"
    p.write_text("not json{", encoding="utf-8")
    assert gate.load_baseline(p) is None


def test_committed_baseline_file_is_valid_and_sane():
    # 同梱の eval/baseline.json は妥当な JSON。未採点なら None、採点済みなら 0–1 の float。
    v = gate.load_baseline(gate._BASELINE_FILE)
    assert v is None or (isinstance(v, float) and 0.0 <= v <= 1.0)


def test_build_baseline_record_shape():
    rec = gate.build_baseline_record(
        {"mean": 0.8, "axis_means": {"axis_expression": 0.8}, "must_fix_violations": 0},
        commit="abc123",
    )
    assert rec["mean"] == 0.8
    assert rec["axis_means"] == {"axis_expression": 0.8}
    assert rec["must_fix_violations"] == 0
    assert rec["commit"] == "abc123"
    assert rec["case_count"] is None
    assert "note" in rec


def test_write_then_load_roundtrip(tmp_path):
    p = tmp_path / "baseline.json"
    rec = gate.build_baseline_record({"mean": 0.812, "axis_means": None, "must_fix_violations": 0})
    gate.write_baseline(rec, p)
    assert gate.load_baseline(p) == 0.812


def test_run_gate_loads_baseline_from_file(tmp_path):
    # baseline.json を読み、no_cases 降格時も baseline_mean を反映する
    baseline = tmp_path / "baseline.json"
    gate.write_baseline({"mean": 0.77, "axis_means": None, "must_fix_violations": 0}, baseline)
    result = gate.run_gate(cases_dir=tmp_path, baseline_path=baseline)  # 空＝no_cases
    assert result["status"] == "no_cases"
    assert result["baseline_mean"] == 0.77


def test_run_gate_explicit_baseline_overrides_file(tmp_path):
    baseline = tmp_path / "baseline.json"
    gate.write_baseline({"mean": 0.5, "axis_means": None, "must_fix_violations": 0}, baseline)
    result = gate.run_gate(cases_dir=tmp_path, baseline_mean=0.9, baseline_path=baseline)
    assert result["baseline_mean"] == 0.9  # 明示値が file より優先


def _write_baseline_record(path: Path, *, mean, axis_means, case_count, gate_policy) -> None:
    gate.write_baseline(
        {
            "mean": mean,
            "axis_means": axis_means,
            "must_fix_violations": 0,
            "case_count": case_count,
            "gate_policy": gate_policy,
        },
        path,
    )


def _write_minimal_evalset(cases_dir: Path, eval_ids: list[str]) -> None:
    data = {
        "eval_set_id": "unit",
        "eval_cases": [{"eval_id": eval_id} for eval_id in eval_ids],
    }
    (cases_dir / "unit.evalset.json").write_text(json.dumps(data), encoding="utf-8")


def test_run_gate_scores_only_with_complete_coverage(monkeypatch, tmp_path):
    _write_minimal_evalset(tmp_path, ["a", "b"])

    async def fake_score(_cases, _agent_module):
        return [_case_score("a"), _case_score("b")]

    monkeypatch.setattr(gate, "_score_cases_with_adk", fake_score)
    result = gate.run_gate(cases_dir=tmp_path, baseline_mean=0.9)
    assert result["status"] == "scored"
    assert result["passed"] is True
    assert result["coverage"]["complete"] is True
    assert result["mean"] == 1.0


def test_run_gate_bootstraps_only_when_candidate_matches_live_result(monkeypatch, tmp_path):
    _write_minimal_evalset(tmp_path, ["a", "b"])
    base = tmp_path / "base.json"
    candidate = tmp_path / "candidate.json"
    gate.write_baseline({"mean": None}, base)
    policy = gate.load_gate_policy()
    _write_baseline_record(
        candidate,
        mean=1.0,
        axis_means={rubric_id: 1.0 for rubric_id in gate.AXIS_RUBRIC_IDS},
        case_count=2,
        gate_policy=policy,
    )

    async def fake_score(_cases, _agent_module):
        return [_case_score("a"), _case_score("b")]

    monkeypatch.setattr(gate, "_score_cases_with_adk", fake_score)
    result = gate.run_gate(
        cases_dir=tmp_path,
        baseline_path=base,
        bootstrap_baseline_path=candidate,
    )
    assert result["passed"] is True
    assert result["baseline_bootstrapped"] is True


def test_run_gate_rejects_bootstrap_candidate_that_differs_from_live_result(monkeypatch, tmp_path):
    _write_minimal_evalset(tmp_path, ["a"])
    base = tmp_path / "base.json"
    candidate = tmp_path / "candidate.json"
    gate.write_baseline({"mean": None}, base)
    _write_baseline_record(
        candidate,
        mean=0.99,
        axis_means={rubric_id: 1.0 for rubric_id in gate.AXIS_RUBRIC_IDS},
        case_count=1,
        gate_policy=gate.load_gate_policy(),
    )

    async def fake_score(_cases, _agent_module):
        return [_case_score("a")]

    monkeypatch.setattr(gate, "_score_cases_with_adk", fake_score)
    result = gate.run_gate(
        cases_dir=tmp_path,
        baseline_path=base,
        bootstrap_baseline_path=candidate,
    )
    assert result["passed"] is None
    assert result["baseline_bootstrapped"] is False


def test_run_gate_ignores_bootstrap_candidate_after_base_is_scored(monkeypatch, tmp_path):
    _write_minimal_evalset(tmp_path, ["a"])
    base = tmp_path / "base.json"
    candidate = tmp_path / "candidate.json"
    gate.write_baseline({"mean": 1.1}, base)
    _write_baseline_record(
        candidate,
        mean=1.0,
        axis_means={rubric_id: 1.0 for rubric_id in gate.AXIS_RUBRIC_IDS},
        case_count=1,
        gate_policy=gate.load_gate_policy(),
    )

    async def fake_score(_cases, _agent_module):
        return [_case_score("a")]

    monkeypatch.setattr(gate, "_score_cases_with_adk", fake_score)
    result = gate.run_gate(
        cases_dir=tmp_path,
        baseline_path=base,
        bootstrap_baseline_path=candidate,
    )
    assert result["passed"] is False
    assert result["baseline_bootstrapped"] is False


def test_run_gate_is_unscored_when_any_rubric_is_missing(monkeypatch, tmp_path):
    _write_minimal_evalset(tmp_path, ["a"])
    missing = _all_pass()
    missing.pop(gate.MUST_FIX_RUBRIC_IDS[0])

    async def fake_score(_cases, _agent_module):
        return [_case_score("a", missing)]

    monkeypatch.setattr(gate, "_score_cases_with_adk", fake_score)
    result = gate.run_gate(cases_dir=tmp_path, baseline_mean=0.9)
    assert result["status"] == "incomplete"
    assert result["passed"] is None
    assert result["coverage"]["missing_rubrics"]["a"] == [gate.MUST_FIX_RUBRIC_IDS[0]]


# ──────────────────────── CLI fail-closed ────────────────────────


def test_exit_code_fails_red_and_strict_unscored():
    assert gate.exit_code_for_result({"passed": True}, strict=True) == 0
    assert gate.exit_code_for_result({"passed": False}, strict=False) == 1
    assert gate.exit_code_for_result({"passed": None}, strict=False) == 0
    assert gate.exit_code_for_result({"passed": None}, strict=True) == 1


def test_eval_workflow_is_fail_closed_and_uses_dedicated_sa():
    workflow = (_REPO_ROOT / ".github" / "workflows" / "eval-gate.yml").read_text(encoding="utf-8")
    assert "--strict" in workflow
    assert "vars.EVAL_SA" in workflow
    assert "vars.DEPLOY_SA" not in workflow
    assert "pytest -q tests/test_eval.py" not in workflow
    assert "github.event.pull_request.base.sha" in workflow
    assert "--baseline-path eval/results/comparison-baseline.json" in workflow
    assert "--bootstrap-baseline-path eval/baseline.json" in workflow
    executable_lines = [line for line in workflow.splitlines() if not line.lstrip().startswith("#")]
    assert not any("--update-baseline" in line for line in executable_lines)
    assert "contents: write" not in workflow
    assert "actions/upload-artifact@v4" in workflow


def test_terraform_declares_least_privilege_eval_runner():
    iam = (_REPO_ROOT / "infra" / "iam.tf").read_text(encoding="utf-8")
    assert 'resource "google_service_account" "eval_runner"' in iam
    assert '"roles/aiplatform.user"' in iam
    assert 'resource "google_service_account_iam_member" "eval_runner_wif"' in iam
