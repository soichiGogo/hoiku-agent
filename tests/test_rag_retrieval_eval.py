"""RAG 検索評価の採点ロジックを、Vertex 接続なしで検証する。"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "evaluate_rag_retrieval.py"
_SPEC = importlib.util.spec_from_file_location("rag_retrieval_eval", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MODULE
_SPEC.loader.exec_module(_MODULE)

RetrievalCase = _MODULE.RetrievalCase
RetrievedChunk = _MODULE.RetrievedChunk
aggregate_case_scores = _MODULE.aggregate_case_scores
choose_winner = _MODULE.choose_winner
load_cases = _MODULE.load_cases
score_case = _MODULE.score_case


def test_cases_are_well_formed() -> None:
    cases = load_cases(Path(__file__).parent / "fixtures" / "rag_retrieval_cases.json")
    assert len(cases) >= 8
    assert len({case.id for case in cases}) == len(cases)


def test_score_case_rewards_expected_source_at_top_and_required_terms() -> None:
    case = RetrievalCase("example", "質問", "告示.pdf", ("個別的な計画", "３歳未満児"))
    result = score_case(
        case,
        [RetrievedChunk("告示.pdf", "３歳未満児については、個別的な計画を作成すること。")],
    )

    assert result["expected_rank"] == 1
    assert result["term_coverage"] == 1.0
    assert result["score"] == 1.0


def test_score_case_marks_missing_source_as_not_hit() -> None:
    case = RetrievalCase("example", "質問", "告示.pdf", ("個別的な計画",))
    result = score_case(case, [RetrievedChunk("解説.pdf", "個別的な計画を作成すること。")])

    assert result["expected_rank"] is None
    assert result["source_rr"] == 0.0
    assert result["score"] == 0.25


def test_choose_winner_prefers_quality_then_smaller_context() -> None:
    base = {"source_hit_rate": 1.0, "mean_source_rr": 1.0, "mean_term_coverage": 1.0}
    winner = choose_winner(
        [
            {"name": "long", "metrics": base | {"mean_score": 0.9, "mean_context_characters": 5000}},
            {"name": "short", "metrics": base | {"mean_score": 0.9, "mean_context_characters": 3000}},
        ]
    )

    assert winner["name"] == "short"


def test_aggregate_case_scores_rejects_empty_input() -> None:
    try:
        aggregate_case_scores([])
    except ValueError as error:
        assert "検索結果がありません" in str(error)
    else:
        raise AssertionError("空の評価結果を受け入れてはいけない")
