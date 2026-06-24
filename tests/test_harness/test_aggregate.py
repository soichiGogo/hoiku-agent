"""harness.aggregate_by_child の単体テスト（LLM 非依存・高速）。

設計コンテキスト §16：月⇔日の決定的集計は pytest で必須。
"""

from __future__ import annotations

from datetime import date

from hoiku_agent.harness import aggregate_by_child
from hoiku_agent.schemas import (
    AgeBand,
    DiaryEntry,
    DiaryEvaluation,
    IndividualNote,
    ThreeViewpoint,
)


def _entry(day: int, child_id: str) -> DiaryEntry:
    return DiaryEntry(
        date=date(2026, 6, day),
        age_band=AgeBand.零から二歳,
        weather="晴れ",
        attendance=[],
        practice_record="記録",
        individual_notes=[
            IndividualNote(
                child_id=child_id,
                observed_state=f"{day}日の姿",
                tags=[ThreeViewpoint.身近な人と気持ちが通じ合う],
            )
        ],
        evaluation=DiaryEvaluation(child_focus="x", self_review="y"),
    )


def test_aggregate_counts_notes_per_child():
    """child_id 別に件数・タグ頻度・観察文が集約される。"""
    digest = aggregate_by_child([_entry(1, "c001"), _entry(2, "c001"), _entry(2, "c002")])
    assert digest["c001"]["note_count"] == 2
    assert digest["c002"]["note_count"] == 1
    assert digest["c001"]["tag_freq"]["身近な人と気持ちが通じ合う"] == 2
    assert len(digest["c001"]["observed_states"]) == 2
