"""fetch_reference の決定的集計と manifest 記録。"""

from __future__ import annotations

from hoiku_agent.harness.reference import fetch_reference_from_state
from hoiku_agent.schemas import (
    AgeBand,
    ChildRecord,
    DevelopmentNote,
    ReferenceSource,
    ThreeViewpoint,
)


def test_missing_candidate_returns_honest_empty_and_manifest():
    state = {}
    result = fetch_reference_from_state(state, ReferenceSource.period_diary)
    assert result["empty"] is True
    assert result["count"] == 0
    assert "データがありません" in result["content"]
    assert state["reference_manifest"] == [{"source": "period_diary", "count": 0, "empty": True}]


def test_fetch_records_digest_and_appends_manifest():
    record = ChildRecord(
        period="2026-04〜2026-06",
        age_band=AgeBand.零から二歳,
        child_id="架空児A",
        development_notes=[
            DevelopmentNote(
                description="探索範囲が広がった",
                tags=[ThreeViewpoint.健やかに伸び伸びと育つ],
            )
        ],
        overall_note="安心して過ごした",
    )
    state = {"prev_record_entries": [record.model_dump(mode="json")]}
    result = fetch_reference_from_state(state, ReferenceSource.prev_child_records)
    assert result["count"] == 1
    assert result["empty"] is False
    assert state["reference_manifest"][0]["source"] == "prev_child_records"
