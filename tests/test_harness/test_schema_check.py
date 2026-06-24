"""harness.validate_fields の単体テスト（LLM 非依存・高速）。

設計コンテキスト §16：LLM 非依存の決定的ロジック（年齢分岐・必須欄）は pytest で必須。
"""

from __future__ import annotations

from datetime import date

from hoiku_agent.harness import validate_fields
from hoiku_agent.schemas import (
    AgeBand,
    DiaryEntry,
    DiaryEvaluation,
    IndividualNote,
    ThreeViewpoint,
)


def _entry(*, tags: list) -> DiaryEntry:
    return DiaryEntry(
        date=date(2026, 6, 25),
        age_band=AgeBand.零から二歳,
        weather="晴れ",
        attendance=[],
        practice_record="散歩で草花に触れた",
        individual_notes=[IndividualNote(child_id="c001", observed_state="花を見つめた", tags=tags)],
        evaluation=DiaryEvaluation(child_focus="興味を示した", self_review="環境構成は適切だった"),
    )


def test_0_2_requires_three_viewpoint_tag():
    """0–2歳で3つの視点タグが無い個別記録は違反になる。"""
    problems = validate_fields(_entry(tags=[]))
    assert any("3つの視点" in p for p in problems)


def test_0_2_with_three_viewpoint_tag_passes():
    """3つの視点タグが付いていれば（少なくともこの観点では）違反は出ない。"""
    problems = validate_fields(_entry(tags=[ThreeViewpoint.健やかに伸び伸び育つ]))
    assert problems == []
