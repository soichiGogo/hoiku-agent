"""層B 評価ゲートの実体（決定的な合否判定）。

設計コンテキスト §12：評価ゲート＝AI版回帰テスト。緑（auto-merge 可）の条件は
**PR の eval 平均が main 比で低下なし、かつ must_fix 違反0**。v0 は「main 平均を下回らない」のみを
ゲートにする（軸別閾値は 15 ケース貯まってから調整）。

採点は ADK ネイティブの rubric メトリクス `rubric_based_final_response_quality_v1` に委ねる
（eval/test_config.json で3軸 axis_*（指針整合/10の姿/保護者向け表現）と mustfix_* を rubric として
配線済み・judge 全文は judges/*.md）。judge（Gemini）が各 rubric を yes/no で評価し、本モジュールが
axis_* の平均をケーススコア、mustfix_* の no を違反として集計して §12 の判定式に落とす。

設計の要（§5/§16）:
- **ゲートの決定ロジック（aggregate_rubric_scores / decide_gate / extract_rubric_scores）は純関数**で
  ここに1つ置き、improver.run_eval / tests/test_eval.py の双方から呼ぶ（二重化しない）。LLM 非依存に
  テストできるよう ADK の採点（要 creds）から切り離す。
- **採点の実行（ADK 駆動）は要 LLM 資格情報**。creds・評価ケースが無い環境では採点できないため、
  `passed=None`（判定不能＝スキップ相当）で安全に降格し、**偽の緑を出さない**。
- **main 比の baseline は committed `eval/baseline.json`**（`load_baseline`/`build_baseline_record`/
  `write_baseline`）。nightly の main eval-gate が `--update-baseline` で更新し、PR は `run_gate` が既定で
  これを読んで非劣化比較する。ファイル不在/壊れは `baseline_mean=None`＝比較なし（must_fix 0 で緑）へ降格。

CLI: `python eval/run_gate.py`（採点して判定）／`python eval/run_gate.py --update-baseline`（main を採点して
baseline.json を更新）。いずれも要 creds。
"""

from __future__ import annotations

import json
from pathlib import Path

_EVAL_DIR = Path(__file__).resolve().parent
_CASES_DIR = _EVAL_DIR / "cases"
_TEST_CONFIG = _EVAL_DIR / "test_config.json"
_BASELINE_FILE = _EVAL_DIR / "baseline.json"

# rubric メトリクス名（test_config.json のキーと一致）と rubric_id 体系（§12 の3軸＋must_fix）。
RUBRIC_METRIC = "rubric_based_final_response_quality_v1"
AXIS_RUBRIC_IDS = ("axis_guideline_alignment", "axis_ten_no_sugata", "axis_expression")
MUST_FIX_RUBRIC_IDS = (
    "mustfix_no_real_names",
    "mustfix_age_framework",
    "mustfix_no_definitive_eval",
)


def find_cases(cases_dir: Path = _CASES_DIR) -> list[Path]:
    """評価ケース（ADK evalset JSON）の一覧を返す。"""
    return sorted(cases_dir.glob("*.evalset.json"))


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
    }


def decide_gate(
    mean: float | None,
    baseline_mean: float | None,
    must_fix_violations: int,
    *,
    tolerance: float = 1e-9,
) -> bool | None:
    """§12 の判定式：main 比 非劣化 かつ must_fix 0 を緑とする（純関数・決定的）。

    Returns:
        True＝緑（非劣化＆違反0）／ False＝赤（劣化 or 違反あり）／ None＝判定不能（採点できていない）。
    v0 は「main 平均を下回らない」のみをゲートにする（baseline_mean=None なら比較対象なしで非劣化扱い）。
    """
    if mean is None:
        return None  # 採点できていない＝判定不能（偽の緑/赤を出さない）
    if must_fix_violations > 0:
        return False  # must_fix 違反は1件でも赤
    if baseline_mean is None:
        return True  # main 比較なし（初回等）＝非劣化として緑（must_fix 0 を確認済み）
    return mean >= baseline_mean - tolerance


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


# ──────────────────── main 比 baseline（committed eval/baseline.json・§12） ────────────────────


def load_baseline(path: Path = _BASELINE_FILE) -> float | None:
    """committed baseline（main の eval 平均）を読む（決定的・LLM 非依存）。

    ファイル不在・壊れ・mean 未記録は **None**（比較対象なし＝非劣化扱いへ降格）にする。読めないことを
    「劣化」と誤認させない（偽の赤を出さない）。`run_gate` が既定でこれを読み PR の非劣化比較に使う。
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


def build_baseline_record(result: dict, *, commit: str | None = None) -> dict:
    """採点結果（run_gate の dict）から baseline レコードを作る（serializable・決定的）。"""
    return {
        "mean": result.get("mean"),
        "axis_means": result.get("axis_means"),
        "must_fix_violations": result.get("must_fix_violations", 0),
        "commit": commit,
        "note": (
            "main の eval 平均（3軸ケース平均）。nightly eval-gate が --update-baseline で更新し、"
            "PR の非劣化比較（decide_gate）に使う＝§12。手で編集しない。"
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


async def _score_cases_with_adk(cases: list[Path], agent_module: str) -> list[dict[str, float]]:
    """各 evalset を ADK でローカル採点し、ケース別 {rubric_id: score} を返す（要 LLM 資格情報）。

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
    app_name = "hoiku_eval"
    per_case: list[dict[str, float]] = []

    for case_path in cases:
        eval_set = EvalSet.model_validate(json.loads(case_path.read_text(encoding="utf-8")))
        manager = InMemoryEvalSetsManager()
        manager.create_eval_set(app_name, eval_set.eval_set_id)
        for case in eval_set.eval_cases:
            manager.add_eval_case(app_name, eval_set.eval_set_id, case)

        service = LocalEvalService(root_agent=root_agent, eval_sets_manager=manager)
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
            per_case.append(extract_rubric_scores(case_result))

    return per_case


def _degraded(status: str, detail: str, baseline_mean: float | None) -> dict:
    return {
        "status": status,
        "passed": None,
        "mean": None,
        "axis_means": None,
        "must_fix_violations": 0,
        "baseline_mean": baseline_mean,
        "detail": detail,
    }


def run_gate(
    cases_dir: Path = _CASES_DIR,
    agent_module: str = "hoiku_agent",
    baseline_mean: float | None = None,
    baseline_path: Path | None = _BASELINE_FILE,
) -> dict:
    """評価ゲートを実行し、合否判定 dict を返す（§12）。

    Args:
        baseline_mean: main 比較の基準値を直に渡す（テスト・improver 用）。None なら baseline_path から読む。
        baseline_path: committed baseline（既定 `eval/baseline.json`）。None で「比較なし」を明示できる。

    Returns:
        {
          "status": "no_cases" | "skipped" | "scored",
          "passed": bool | None,        # None＝判定不能（採点不可・未配線で降格）
          "mean": float | None,         # 3軸ケース平均（採点できた場合）
          "axis_means": dict | None,    # 軸別平均（採点できた場合）
          "must_fix_violations": int,
          "baseline_mean": float | None,
          "detail": str,
        }

    挙動（§12 の判定式）：rubric メトリクス（test_config.json）で各ケースを採点し、axis_* 平均を
    ケーススコア、mustfix_* の no を違反として集計 → `decide_gate`（main 比 非劣化 かつ must_fix 0）で
    passed を確定する。比較基準は committed `eval/baseline.json`（`load_baseline`）を既定で読む（PR は main の
    平均と比べる）。**採点できない場合（ケース未整備／LLM 資格情報なし／ADK 例外）は passed=None で
    降格し、偽の緑を出さない**。
    """
    # main 比の基準（baseline）を確定する：明示値が無ければ committed baseline.json から読む（無ければ None）。
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
        import asyncio

        import google.adk.evaluation  # noqa: F401  ADK evaluation の有無を先に確認
    except ImportError as e:
        return _degraded("skipped", f"google-adk evaluation 未利用: {e}", baseline_mean)

    try:
        per_case = asyncio.run(_score_cases_with_adk(cases, agent_module))
    except Exception as e:  # noqa: BLE001  資格情報なし等は判定不能として降格（ゲートを落とさない）
        return _degraded(
            "skipped",
            f"採点を実行できませんでした（資格情報/モデル未設定の可能性）: {type(e).__name__}: {e}",
            baseline_mean,
        )

    agg = aggregate_rubric_scores(per_case)
    passed = decide_gate(agg["mean"], baseline_mean, agg["must_fix_violations"])
    if passed is None:
        # ケースは回ったが rubric スコアを取り出せなかった（judge 応答異常等）＝判定不能で降格。
        return _degraded(
            "skipped",
            f"{len(cases)} ケースを採点したが rubric スコアを取得できず判定不能。",
            baseline_mean,
        )
    return {
        "status": "scored",
        "passed": passed,
        "mean": agg["mean"],
        "axis_means": agg["axis_means"],
        "must_fix_violations": agg["must_fix_violations"],
        "baseline_mean": baseline_mean,
        "detail": (
            f"{agg['n_scored']} ケースを3軸採点（mean={agg['mean']:.3f}）／"
            f"must_fix 違反={agg['must_fix_violations']}／"
            f"判定={'緑' if passed else '赤'}（main 比 非劣化 かつ must_fix 0）。"
        ),
    }


def update_baseline(
    cases_dir: Path = _CASES_DIR,
    agent_module: str = "hoiku_agent",
    baseline_path: Path = _BASELINE_FILE,
    commit: str | None = None,
) -> dict:
    """main を採点して baseline.json を更新する（要 creds・nightly/手動で実行＝§12）。

    比較はせず素の採点だけ行い（baseline_path=None）、採点できた場合のみ baseline を上書きする。採点不能
    （creds/ケース/依存なし）なら **書かずに** status を返す（古い baseline を壊さない＝偽の更新をしない）。
    """
    result = run_gate(cases_dir, agent_module, baseline_path=None)
    if result["mean"] is None:
        return {
            "status": "not_updated",
            "reason": result["status"],
            "detail": f"採点できず baseline 据え置き: {result['detail']}",
        }
    write_baseline(build_baseline_record(result, commit=commit), baseline_path)
    return {
        "status": "updated",
        "mean": result["mean"],
        "path": str(baseline_path),
        "detail": (
            f"baseline 更新（mean={result['mean']:.3f}・must_fix={result['must_fix_violations']}）。"
        ),
    }


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="層B 評価ゲート（採点 or baseline 更新）")
    ap.add_argument(
        "--update-baseline",
        action="store_true",
        help="main を採点して eval/baseline.json を更新する（nightly/手動・要 creds）",
    )
    ap.add_argument("--commit", default=None, help="baseline に記録する commit SHA（任意）")
    args = ap.parse_args()
    result = update_baseline(commit=args.commit) if args.update_baseline else run_gate()
    print(json.dumps(result, ensure_ascii=False, indent=2))
