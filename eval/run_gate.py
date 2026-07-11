"""層B 評価ゲートの実体（決定的な合否判定）。

設計コンテキスト §12：評価ゲート＝AI版回帰テスト。緑（auto-merge 可）の条件は
**全ケース・全 rubric の採点完了、品質 floor 達成、PR の eval 平均が main 比の非劣化マージン内、かつ
must_fix 違反0**。採点不能や baseline 未確立を成功に読み替えない（CI は strict で fail-closed）。

採点は ADK ネイティブの rubric メトリクス `rubric_based_final_response_quality_v1` に委ねる
（eval/test_config.json で3軸 axis_*（指針整合/10の姿/保護者向け表現）と mustfix_* を rubric として
配線済み・judge 全文は judges/*.md）。judge（Gemini）が各 rubric を yes/no で評価し、本モジュールが
axis_* の平均をケーススコア、mustfix_* の no を違反として集計して §12 の判定式に落とす。

設計の要（§5/§16）:
- **ゲートの決定ロジック（aggregate_rubric_scores / decide_gate / extract_rubric_scores）は純関数**で
  ここに1つ置き、improver.run_eval / tests/test_eval.py の双方から呼ぶ（二重化しない）。LLM 非依存に
  テストできるよう ADK の採点（要 creds）から切り離す。
- **採点の実行（ADK 駆動）は要 LLM 資格情報**。ローカル API としては採点不能を `passed=None` で
  表現するが、CI は `--strict` で非0終了にする。rubric の一部欠落も判定不能であり、present のみを
  平均して成功扱いしない。
- **main 比の baseline は committed `eval/baseline.json`**（`load_baseline`/`build_baseline_record`/
  `write_baseline`）。更新は人が意図して `--update-baseline` を実行し、通常の PR レビューで取り込む。
  nightly に基準を自動追随させない。ファイル不在/壊れ/mean=null は判定不能（strict では赤）。

CLI: `python eval/run_gate.py`（採点して判定）／`python eval/run_gate.py --update-baseline`（main を採点して
baseline.json を更新）。いずれも要 creds。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
from typing import Any

_EVAL_DIR = Path(__file__).resolve().parent
_CASES_DIR = _EVAL_DIR / "cases"
_TEST_CONFIG = _EVAL_DIR / "test_config.json"
_BASELINE_FILE = _EVAL_DIR / "baseline.json"
_GATE_POLICY_FILE = _EVAL_DIR / "gate_policy.json"

# rubric メトリクス名（test_config.json のキーと一致）と rubric_id 体系（§12 の3軸＋must_fix）。
RUBRIC_METRIC = "rubric_based_final_response_quality_v1"
AXIS_RUBRIC_IDS = ("axis_guideline_alignment", "axis_ten_no_sugata", "axis_expression")
MUST_FIX_RUBRIC_IDS = (
    "mustfix_no_real_names",
    "mustfix_age_framework",
    "mustfix_no_definitive_eval",
)
REQUIRED_RUBRIC_IDS = AXIS_RUBRIC_IDS + MUST_FIX_RUBRIC_IDS

_AUTORATER_BLOCK_PATTERN = re.compile(
    r"^Property:\s*(?P<property>.*?)\n"
    r"^Evidence:\s*.*?\n"
    r"^Rationale:\s*(?P<rationale>.*?)\n"
    r"^Verdict:\s*(?P<verdict>yes|no)\s*(?=^Property:|\Z)",
    flags=re.MULTILINE | re.DOTALL | re.IGNORECASE,
)


def find_cases(cases_dir: Path = _CASES_DIR) -> list[Path]:
    """評価ケース（ADK evalset JSON）の一覧を返す。"""
    return sorted(cases_dir.glob("*.evalset.json"))


def load_expected_case_ids(cases: list[Path]) -> list[str]:
    """evalset JSON から期待する全 eval_id を読み出す（coverage の正）。"""
    ids: list[str] = []
    for path in cases:
        data = json.loads(path.read_text(encoding="utf-8"))
        ids.extend(str(case["eval_id"]) for case in data.get("eval_cases", []))
    return ids


def load_gate_policy(path: Path = _GATE_POLICY_FILE) -> dict[str, Any]:
    """決定的な品質 floor を読む。壊れた設定はゲート構成エラーとして例外にする。"""
    data = json.loads(path.read_text(encoding="utf-8"))
    axis_minimums = data.get("axis_minimums")
    if not isinstance(axis_minimums, dict) or set(axis_minimums) != set(AXIS_RUBRIC_IDS):
        raise ValueError("gate_policy.axis_minimums は3軸すべてを定義する必要があります")
    for rubric_id, value in axis_minimums.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 1:
            raise ValueError(f"gate_policy.axis_minimums.{rubric_id} は0–1で指定してください")
    case_minimum = data.get("case_minimum")
    if (
        isinstance(case_minimum, bool)
        or not isinstance(case_minimum, (int, float))
        or not 0 <= case_minimum <= 1
    ):
        raise ValueError("gate_policy.case_minimum は0–1で指定してください")
    non_inferiority_margin = data.get("non_inferiority_margin")
    if (
        isinstance(non_inferiority_margin, bool)
        or not isinstance(non_inferiority_margin, (int, float))
        or not 0 <= non_inferiority_margin <= 1
    ):
        raise ValueError("gate_policy.non_inferiority_margin は0–1で指定してください")
    return {
        "axis_minimums": {key: float(value) for key, value in axis_minimums.items()},
        "case_minimum": float(case_minimum),
        "non_inferiority_margin": float(non_inferiority_margin),
    }


def parse_autorater_blocks(text: str) -> list[dict[str, Any]]:
    """ADK judge の Property/Evidence/Rationale/Verdict ブロックを複数行対応で読む。

    ADK 2.3 の既定 parser は Rationale が同じ行にある場合しか拾えず、judge が自然に改行すると
    全 rubric が欠落する。外部 package をpatchせず、同じ公開出力契約を堅牢に解釈するadapterの純関数。
    """
    parsed: list[dict[str, Any]] = []
    for match in _AUTORATER_BLOCK_PATTERN.finditer(text):
        parsed.append(
            {
                "property": match.group("property").strip(),
                "rationale": match.group("rationale").strip(),
                "score": 1.0 if match.group("verdict").lower() == "yes" else 0.0,
            }
        )
    return parsed


def _build_metric_registry():
    """ADK 2.3 rubric evaluatorへ堅牢parserを差し込んだ、このゲート専用registryを作る。"""
    from google.adk.evaluation.metric_evaluator_registry import MetricEvaluatorRegistry
    from google.adk.evaluation.metric_info_providers import (
        RubricBasedFinalResponseQualityV1EvaluatorMetricInfoProvider,
    )
    from google.adk.evaluation.rubric_based_evaluator import AutoRaterResponseParser
    from google.adk.evaluation.rubric_based_evaluator import RubricResponse
    from google.adk.evaluation.rubric_based_final_response_quality_v1 import (
        RubricBasedFinalResponseQualityV1Evaluator,
    )

    class MarkerAwareMultilineParser(AutoRaterResponseParser):
        def __init__(self, canonical_properties: dict[str, str]):
            self._canonical_properties = canonical_properties

        def parse(self, auto_rater_response: str) -> list[RubricResponse]:
            responses: list[RubricResponse] = []
            for block in parse_autorater_blocks(auto_rater_response):
                property_text = block["property"]
                for rubric_id, canonical in self._canonical_properties.items():
                    if f"[{rubric_id}]" in property_text:
                        property_text = canonical
                        break
                responses.append(
                    RubricResponse(
                        property_text=property_text,
                        rationale=block["rationale"],
                        score=block["score"],
                    )
                )
            return responses

    class RobustRubricEvaluator(RubricBasedFinalResponseQualityV1Evaluator):
        def __init__(self, eval_metric):
            super().__init__(eval_metric)
            canonical = {
                rubric.rubric_id: rubric.rubric_content.text_property for rubric in self._rubrics
            }
            self._auto_rater_response_parser = MarkerAwareMultilineParser(canonical)

    registry = MetricEvaluatorRegistry()
    registry.register_evaluator(
        metric_info=RubricBasedFinalResponseQualityV1EvaluatorMetricInfoProvider().get_metric_info(),
        evaluator=RobustRubricEvaluator,
    )
    return registry


# ──────────────────── ゲートの決定ロジック（純関数・§12・LLM 非依存） ────────────────────


def aggregate_rubric_scores(
    per_case_scores: list[dict[str, float]],
    axis_ids: tuple[str, ...] = AXIS_RUBRIC_IDS,
    must_fix_ids: tuple[str, ...] = MUST_FIX_RUBRIC_IDS,
) -> dict:
    """ケース別の rubric スコア（{rubric_id: 0–1}）を §12 の集計へ落とす（純関数・決定的）。

    - ケーススコア＝そのケースに存在する axis_* rubric の平均（0–1）。
    - 全体 mean＝ケーススコアの平均（採点できたケースが無ければ None）。
    - axis_means＝軸別の平均（軸別閾値調整・可視化用）。
    - must_fix_violations＝mustfix_* rubric が "no"（< 1.0）だった回数の総和。

    Args:
        per_case_scores: ケースごとの {rubric_id: score} のリスト。
        axis_ids: ケーススコアを成す3軸 rubric の id。
        must_fix_ids: 違反として数える must_fix rubric の id。

    Returns:
        {"mean", "axis_means", "must_fix_violations", "n_scored"}。
    """
    case_means: list[float] = []
    axis_accum: dict[str, list[float]] = {a: [] for a in axis_ids}
    must_fix_violations = 0

    for scores in per_case_scores:
        present = [scores[a] for a in axis_ids if scores.get(a) is not None]
        if present:
            case_means.append(sum(present) / len(present))
        for a in axis_ids:
            if scores.get(a) is not None:
                axis_accum[a].append(scores[a])
        for m in must_fix_ids:
            v = scores.get(m)
            if v is not None and v < 1.0:  # must_fix rubric の "no"（不充足）＝違反
                must_fix_violations += 1

    mean = sum(case_means) / len(case_means) if case_means else None
    axis_means = {a: (sum(v) / len(v) if v else None) for a, v in axis_accum.items()}
    return {
        "mean": mean,
        "axis_means": axis_means,
        "must_fix_violations": must_fix_violations,
        "n_scored": len(case_means),
        "case_means": case_means,
    }


def validate_score_coverage(
    case_results: list[dict[str, Any]],
    expected_case_ids: list[str],
    required_rubric_ids: tuple[str, ...] = REQUIRED_RUBRIC_IDS,
) -> dict[str, Any]:
    """全ケース×全 rubric が一度ずつ採点されたことを検査する（純関数・fail-closed）。"""
    actual_ids = [str(result.get("eval_id") or "") for result in case_results]
    expected_set = set(expected_case_ids)
    actual_set = set(actual_ids)
    duplicates = sorted({eval_id for eval_id in actual_ids if actual_ids.count(eval_id) > 1})
    missing_rubrics: dict[str, list[str]] = {}
    for result in case_results:
        eval_id = str(result.get("eval_id") or "<unknown>")
        scores = result.get("scores") if isinstance(result.get("scores"), dict) else {}
        missing = [rubric_id for rubric_id in required_rubric_ids if scores.get(rubric_id) is None]
        if missing:
            missing_rubrics[eval_id] = missing
    missing_cases = sorted(expected_set - actual_set)
    unexpected_cases = sorted(actual_set - expected_set)
    complete = bool(expected_case_ids) and not (
        duplicates or missing_cases or unexpected_cases or missing_rubrics or "" in actual_set
    )
    return {
        "complete": complete,
        "expected_cases": len(expected_case_ids),
        "scored_cases": len(case_results),
        "missing_cases": missing_cases,
        "unexpected_cases": unexpected_cases,
        "duplicate_cases": duplicates,
        "missing_rubrics": missing_rubrics,
    }


def evaluate_quality_floors(
    case_results: list[dict[str, Any]],
    aggregate: dict[str, Any],
    policy: dict[str, Any],
) -> dict[str, Any]:
    """軸別・ケース別の絶対 floor 違反を返す（純関数・baseline比較とは独立）。"""
    failures: list[str] = []
    case_means: dict[str, float] = {}
    for rubric_id, minimum in policy["axis_minimums"].items():
        actual = aggregate["axis_means"].get(rubric_id)
        if actual is None or actual < minimum:
            failures.append(f"{rubric_id}={actual} < floor={minimum}")
    case_minimum = policy["case_minimum"]
    for result in case_results:
        scores = result["scores"]
        case_mean = sum(scores[rubric_id] for rubric_id in AXIS_RUBRIC_IDS) / len(AXIS_RUBRIC_IDS)
        case_means[str(result["eval_id"])] = case_mean
        if case_mean < case_minimum:
            failures.append(
                f"{result['eval_id']}: case_mean={case_mean:.3f} < floor={case_minimum:.3f}"
            )
    return {"failures": failures, "case_means": case_means}


def decide_gate(
    mean: float | None,
    baseline_mean: float | None,
    must_fix_violations: int,
    *,
    non_inferiority_margin: float = 0.0,
) -> bool | None:
    """§12 の判定式：main 比の許容幅内かつ must_fix 0 を緑とする（純関数・決定的）。

    Returns:
        True＝緑（許容幅内＆違反0）／ False＝赤（有意な劣化 or 違反あり）／ None＝判定不能。
    baseline が無い状態は非劣化を証明できないため None（判定不能）とする。
    """
    if mean is None:
        return None  # 採点できていない＝判定不能（偽の緑/赤を出さない）
    if must_fix_violations > 0:
        return False  # must_fix 違反は1件でも赤
    if baseline_mean is None:
        return None  # 基準未確立＝判定不能（CI strict では赤）
    return mean >= baseline_mean - non_inferiority_margin


def extract_rubric_scores(eval_case_result: object) -> dict[str, float]:
    """ADK の EvalCaseResult から rubric_id→score（0–1）を取り出す（決定的・shape 不一致は空）。

    overall_eval_metric_results の中から rubric メトリクスの details.rubric_scores を拾う。ADK の
    結果型に依存するが、純粋な抽出のみで LLM は呼ばない（合成オブジェクトでテスト可）。
    """
    scores: dict[str, float] = {}
    for metric_result in getattr(eval_case_result, "overall_eval_metric_results", None) or []:
        if getattr(metric_result, "metric_name", None) != RUBRIC_METRIC:
            continue
        details = getattr(metric_result, "details", None)
        for rubric_score in getattr(details, "rubric_scores", None) or []:
            rid = getattr(rubric_score, "rubric_id", None)
            score = getattr(rubric_score, "score", None)
            if rid is not None and score is not None:
                scores[rid] = float(score)
    return scores


def extract_rubric_rationales(eval_case_result: object) -> dict[str, str]:
    """ADK の EvalCaseResult から rubric_id→judge理由を取り出す（artifact用）。"""
    rationales: dict[str, str] = {}
    for invocation_result in (
        getattr(eval_case_result, "eval_metric_result_per_invocation", None) or []
    ):
        for metric_result in getattr(invocation_result, "eval_metric_results", None) or []:
            if getattr(metric_result, "metric_name", None) != RUBRIC_METRIC:
                continue
            details = getattr(metric_result, "details", None)
            for rubric_score in getattr(details, "rubric_scores", None) or []:
                rubric_id = getattr(rubric_score, "rubric_id", None)
                rationale = getattr(rubric_score, "rationale", None)
                if rubric_id is not None and rationale:
                    rationales[str(rubric_id)] = str(rationale)
    if rationales:
        return rationales
    for metric_result in getattr(eval_case_result, "overall_eval_metric_results", None) or []:
        if getattr(metric_result, "metric_name", None) != RUBRIC_METRIC:
            continue
        details = getattr(metric_result, "details", None)
        for rubric_score in getattr(details, "rubric_scores", None) or []:
            rubric_id = getattr(rubric_score, "rubric_id", None)
            rationale = getattr(rubric_score, "rationale", None)
            if rubric_id is not None and rationale:
                rationales[str(rubric_id)] = str(rationale)
    return rationales


# ──────────────────── main 比 baseline（committed eval/baseline.json・§12） ────────────────────


def load_baseline(path: Path = _BASELINE_FILE) -> float | None:
    """committed baseline（main の eval 平均）を読む（決定的・LLM 非依存）。

    ファイル不在・壊れ・mean 未記録は **None**（判定不能）にする。`run_gate` が既定でこれを読み、
    CI の strict モードでは基準未確立を失敗にする。
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    mean = data.get("mean") if isinstance(data, dict) else None
    # bool は int のサブクラスなので除外（True/False を 1.0/0.0 と誤読しない）。
    if isinstance(mean, bool) or not isinstance(mean, (int, float)):
        return None
    return float(mean)


def load_baseline_record(path: Path) -> dict[str, Any] | None:
    """baseline JSON をレコードとして読む。欠損・壊れ・非objectは None。"""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def baseline_record_matches_result(
    record: dict[str, Any],
    *,
    aggregate: dict[str, Any],
    coverage: dict[str, Any],
    gate_policy: dict[str, Any],
) -> bool:
    """初回 bootstrap 用 baseline が今回の完全採点結果と一致するか決定的に検証する。

    commit/note は採点値ではないため比較対象外。数値・軸別平均・違反数・ケース数・ゲート方針が
    すべて一致した場合だけ true とし、未採点 main から任意の基準値を持ち込めないようにする。
    """
    mean = record.get("mean")
    if isinstance(mean, bool) or not isinstance(mean, (int, float)):
        return False
    return (
        float(mean) == aggregate.get("mean")
        and record.get("axis_means") == aggregate.get("axis_means")
        and record.get("must_fix_violations") == aggregate.get("must_fix_violations") == 0
        and record.get("case_count") == coverage.get("scored_cases")
        and record.get("gate_policy") == gate_policy
    )


def build_baseline_record(result: dict, *, commit: str | None = None) -> dict:
    """採点結果（run_gate の dict）から baseline レコードを作る（serializable・決定的）。"""
    return {
        "mean": result.get("mean"),
        "axis_means": result.get("axis_means"),
        "must_fix_violations": result.get("must_fix_violations", 0),
        "commit": commit,
        "case_count": (result.get("coverage") or {}).get("scored_cases"),
        "gate_policy": result.get("gate_policy"),
        "note": (
            "main の eval 平均（3軸ケース平均）。意図的な --update-baseline 採点を通常PRでレビューし、"
            "PR の非劣化比較（decide_gate）に使う＝§12。nightly は自動更新しない。"
        ),
    }


def write_baseline(record: dict, path: Path = _BASELINE_FILE) -> None:
    """baseline レコードを committed JSON として書き出す（末尾改行つき・人間可読）。"""
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


# ──────────────────── ADK 駆動の採点（要 creds・降格付き） ────────────────────


def _load_eval_metrics() -> list:
    """eval/test_config.json から rubric メトリクス（EvalMetric）を構築する（creds 不要）。"""
    from google.adk.evaluation.eval_config import (
        get_eval_metrics_from_config,
        get_evaluation_criteria_or_default,
    )

    eval_config = get_evaluation_criteria_or_default(str(_TEST_CONFIG))
    return get_eval_metrics_from_config(eval_config)


async def _score_cases_with_adk(cases: list[Path], agent_module: str) -> list[dict[str, Any]]:
    """各 evalset を ADK でローカル採点し、ケース別の採点証跡を返す（要 LLM 資格情報）。

    LocalEvalService に root_agent と evalset を渡し、推論→rubric 採点を回す。inference/採点は judge
    モデル（Gemini）を呼ぶため資格情報が要る。呼び出し側（run_gate）が例外を握って降格する。
    """
    import importlib

    from google.adk.evaluation.base_eval_service import (
        EvaluateConfig,
        EvaluateRequest,
        InferenceConfig,
        InferenceRequest,
    )
    from google.adk.evaluation.eval_set import EvalSet
    from google.adk.evaluation.in_memory_eval_sets_manager import InMemoryEvalSetsManager
    from google.adk.evaluation.local_eval_service import LocalEvalService

    root_agent = importlib.import_module(agent_module).root_agent
    eval_metrics = _load_eval_metrics()
    metric_registry = _build_metric_registry()
    app_name = "hoiku_eval"
    per_case: list[dict[str, Any]] = []

    for case_path in cases:
        eval_set = EvalSet.model_validate(json.loads(case_path.read_text(encoding="utf-8")))
        manager = InMemoryEvalSetsManager()
        manager.create_eval_set(app_name, eval_set.eval_set_id)
        for case in eval_set.eval_cases:
            manager.add_eval_case(app_name, eval_set.eval_set_id, case)

        service = LocalEvalService(
            root_agent=root_agent,
            eval_sets_manager=manager,
            metric_evaluator_registry=metric_registry,
        )
        inference_results = [
            r
            async for r in service.perform_inference(
                inference_request=InferenceRequest(
                    app_name=app_name,
                    eval_set_id=eval_set.eval_set_id,
                    inference_config=InferenceConfig(),
                )
            )
        ]
        async for case_result in service.evaluate(
            evaluate_request=EvaluateRequest(
                inference_results=inference_results,
                evaluate_config=EvaluateConfig(eval_metrics=eval_metrics),
            )
        ):
            per_case.append(
                {
                    "eval_id": str(getattr(case_result, "eval_id", "")),
                    "scores": extract_rubric_scores(case_result),
                    "rationales": extract_rubric_rationales(case_result),
                }
            )

    return per_case


def _degraded(
    status: str,
    detail: str,
    baseline_mean: float | None,
    *,
    coverage: dict[str, Any] | None = None,
    case_results: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "status": status,
        "passed": None,
        "mean": None,
        "axis_means": None,
        "must_fix_violations": 0,
        "baseline_mean": baseline_mean,
        "coverage": coverage,
        "quality_failures": [],
        "case_results": case_results or [],
        "detail": detail,
    }


def run_gate(
    cases_dir: Path = _CASES_DIR,
    agent_module: str = "hoiku_agent",
    baseline_mean: float | None = None,
    baseline_path: Path | None = _BASELINE_FILE,
    bootstrap_baseline_path: Path | None = None,
) -> dict[str, Any]:
    """評価ゲートを実行し、合否判定 dict を返す（§12）。

    Args:
        baseline_mean: main 比較の基準値を直に渡す（テスト・improver 用）。None なら baseline_path から読む。
        baseline_path: committed baseline（既定 `eval/baseline.json`）。None で「比較なし」を明示できる。
        bootstrap_baseline_path: base baseline の mean が明示的に null の初回だけ、今回の実採点値との
            完全一致を検証する候補 baseline。通常の比較では使わない。

    Returns:
        {
          "status": "no_cases" | "skipped" | "incomplete" | "scored",
          "passed": bool | None,        # None＝判定不能（採点不可・未配線で降格）
          "mean": float | None,         # 3軸ケース平均（採点できた場合）
          "axis_means": dict | None,    # 軸別平均（採点できた場合）
          "must_fix_violations": int,
          "baseline_mean": float | None,
          "detail": str,
        }

    挙動（§12 の判定式）：rubric メトリクス（test_config.json）で各ケースを採点し、axis_* 平均を
    ケーススコア、mustfix_* の no を違反として集計 → `decide_gate`（main 比の許容幅内 かつ must_fix 0）で
    passed を確定する。比較基準は committed `eval/baseline.json`（`load_baseline`）を既定で読む（PR は main の
    平均と比べる）。採点不能・baseline 未確立・一部ケース/rubric 欠落は passed=None。CLI の `--strict`
    はこれを非0終了へ変換し、CI で fail-closed にする。
    """
    # main 比の基準（baseline）を確定する：明示値が無ければ committed baseline.json から読む（無ければ None）。
    baseline_record = load_baseline_record(baseline_path) if baseline_path is not None else None
    if baseline_mean is None and baseline_path is not None:
        baseline_mean = load_baseline(baseline_path)

    cases = find_cases(cases_dir)
    if not cases:
        return _degraded(
            "no_cases",
            "評価ケース未整備（eval/cases/*.evalset.json を追加すると有効化）。",
            baseline_mean,
        )

    try:
        expected_case_ids = load_expected_case_ids(cases)
        gate_policy = load_gate_policy()
    except (OSError, KeyError, TypeError, ValueError) as e:
        return _degraded("config_error", f"eval 構成を読めませんでした: {e}", baseline_mean)

    if not expected_case_ids or len(expected_case_ids) != len(set(expected_case_ids)):
        return _degraded(
            "config_error",
            "eval_id が空、または evalset 間で重複しています。",
            baseline_mean,
        )

    try:
        import asyncio

        import google.adk.evaluation  # noqa: F401  ADK evaluation の有無を先に確認
    except ImportError as e:
        return _degraded("skipped", f"google-adk evaluation 未利用: {e}", baseline_mean)

    try:
        per_case = asyncio.run(_score_cases_with_adk(cases, agent_module))
    except Exception as e:  # noqa: BLE001  API は判定不能、CI strict は非0終了
        return _degraded(
            "skipped",
            f"採点を実行できませんでした（資格情報/モデル未設定の可能性）: {type(e).__name__}: {e}",
            baseline_mean,
        )

    coverage = validate_score_coverage(per_case, expected_case_ids)
    if not coverage["complete"]:
        return _degraded(
            "incomplete",
            "全ケース×全rubricの採点が完了していません。欠落を無視せず判定不能とします。",
            baseline_mean,
            coverage=coverage,
            case_results=per_case,
        )

    score_maps = [result["scores"] for result in per_case]
    agg = aggregate_rubric_scores(score_maps)
    floor_result = evaluate_quality_floors(per_case, agg, gate_policy)
    quality_failures = floor_result["failures"]
    per_case = [
        {**result, "case_mean": floor_result["case_means"][result["eval_id"]]}
        for result in per_case
    ]
    if agg["must_fix_violations"]:
        quality_failures.append(f"must_fix 違反={agg['must_fix_violations']}")

    margin = gate_policy["non_inferiority_margin"]
    comparison = decide_gate(
        agg["mean"],
        baseline_mean,
        agg["must_fix_violations"],
        non_inferiority_margin=margin,
    )
    bootstrapped = False
    # 初回導入PRに限る例外。base側に「mean: null」が明記され、候補baselineが今回の実採点結果と
    # 完全一致する場合だけ比較成立とする。baseが採点済みになった後は候補側baselineを無視する。
    if (
        comparison is None
        and baseline_record is not None
        and "mean" in baseline_record
        and baseline_record.get("mean") is None
        and bootstrap_baseline_path is not None
    ):
        bootstrap_record = load_baseline_record(bootstrap_baseline_path)
        bootstrapped = bootstrap_record is not None and baseline_record_matches_result(
            bootstrap_record,
            aggregate=agg,
            coverage=coverage,
            gate_policy=gate_policy,
        )
        if bootstrapped:
            comparison = True
    if comparison is False and agg["must_fix_violations"] == 0:
        threshold = baseline_mean - margin
        quality_failures.append(
            f"mean={agg['mean']:.3f} < baseline-margin={threshold:.3f} "
            f"（baseline={baseline_mean:.3f}, margin={margin:.3f}）"
        )
    passed = None if comparison is None else not quality_failures
    verdict = "判定不能" if passed is None else ("緑" if passed else "赤")
    if bootstrapped:
        detail_suffix = "初回baselineが実採点結果と完全一致・coverage 100%・floor達成・must_fix 0。"
    elif baseline_mean is None:
        detail_suffix = "baseline 未確立のため判定不能（--update-baseline で意図的に確立する）。"
    elif quality_failures:
        detail_suffix = "／".join(quality_failures)
    else:
        detail_suffix = (
            f"coverage 100%・floor達成・main比の非劣化マージン{margin:.3f}以内・must_fix 0。"
        )
    return {
        "status": "scored",
        "passed": passed,
        "mean": agg["mean"],
        "axis_means": agg["axis_means"],
        "must_fix_violations": agg["must_fix_violations"],
        "baseline_mean": baseline_mean,
        "baseline_bootstrapped": bootstrapped,
        "coverage": coverage,
        "quality_failures": quality_failures,
        "gate_policy": gate_policy,
        "case_results": per_case,
        "detail": (
            f"{agg['n_scored']} ケースを3軸採点（mean={agg['mean']:.3f}）／"
            f"must_fix 違反={agg['must_fix_violations']}／"
            f"判定={verdict}。{detail_suffix}"
        ),
    }


def update_baseline(
    cases_dir: Path = _CASES_DIR,
    agent_module: str = "hoiku_agent",
    baseline_path: Path = _BASELINE_FILE,
    commit: str | None = None,
) -> dict[str, Any]:
    """main を採点して baseline.json を意図的に更新する（要 creds・手動実行＝§12）。

    比較はせず素の採点だけ行う。coverage 100%・品質 floor・must_fix 0 の場合だけ上書きする。
    nightly からは呼ばず、変更をレビュー可能な通常コミットとして取り込む。
    """
    result = run_gate(cases_dir, agent_module, baseline_path=None)
    if (
        result["status"] != "scored"
        or result["mean"] is None
        or result["must_fix_violations"] > 0
        or result["quality_failures"]
        or not (result.get("coverage") or {}).get("complete")
    ):
        return {
            "status": "not_updated",
            "reason": result["status"],
            "result": result,
            "detail": f"完全で合格品質の採点ではないため baseline 据え置き: {result['detail']}",
        }
    write_baseline(build_baseline_record(result, commit=commit), baseline_path)
    return {
        "status": "updated",
        "mean": result["mean"],
        "path": str(baseline_path),
        "result": result,
        "detail": (
            f"baseline 更新（mean={result['mean']:.3f}・must_fix={result['must_fix_violations']}）。"
        ),
    }


def exit_code_for_result(result: dict[str, Any], *, strict: bool) -> int:
    """CLI 終了コードを返す。赤は常に失敗、判定不能は strict 時だけ失敗。"""
    if result.get("status") == "updated":
        return 0
    passed = result.get("passed")
    if passed is True:
        return 0
    if passed is False:
        return 1
    return 1 if strict else 0


def _write_result(result: dict[str, Any], output: Path | None) -> None:
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")


if __name__ == "__main__":
    # .env を os.environ に展開する。judge（rubric LLM）の genai client は env で Vertex/AI Studio を
    # 判定するため、未 export だと "No API key" で全ケース採点不能→ baseline が silently 据え置きになる
    # （実機で踏んだ）。pydantic settings（env_file）は os.environ を埋めないので別途必要。CI は実 env を
    # 使うので override=False（既存 env を壊さない）。.env が無ければ no-op。
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass

    ap = argparse.ArgumentParser(description="層B 評価ゲート（採点 or baseline 更新）")
    ap.add_argument(
        "--update-baseline",
        action="store_true",
        help="main を採点して eval/baseline.json を意図的に更新する（手動・要 creds）",
    )
    ap.add_argument("--commit", default=None, help="baseline に記録する commit SHA（任意）")
    ap.add_argument(
        "--strict",
        action="store_true",
        help="採点不能・baseline未確立も非0終了にする（CIでは必須）",
    )
    ap.add_argument(
        "--output", type=Path, default=None, help="結果JSONの保存先（Actions artifact用）"
    )
    ap.add_argument(
        "--baseline-path",
        type=Path,
        default=_BASELINE_FILE,
        help="比較するbaseline JSON（PR CIはbase SHAから抽出したファイルを渡す）",
    )
    ap.add_argument(
        "--bootstrap-baseline-path",
        type=Path,
        default=None,
        help="base baselineがmean=nullの初回だけ実採点との完全一致を検証する候補baseline",
    )
    args = ap.parse_args()
    result = (
        update_baseline(commit=args.commit)
        if args.update_baseline
        else run_gate(
            baseline_path=args.baseline_path,
            bootstrap_baseline_path=args.bootstrap_baseline_path,
        )
    )
    _write_result(result, args.output)
    raise SystemExit(exit_code_for_result(result, strict=args.strict or args.update_baseline))
