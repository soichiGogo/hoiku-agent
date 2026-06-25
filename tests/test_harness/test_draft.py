"""harness.write_draft の単体テスト（LLM 非依存）。

設計コンテキスト §13：10の姿/3つの視点タグを明示出力することを担保する。
"""

from __future__ import annotations

from datetime import date

from hoiku_agent.harness import write_draft
from hoiku_agent.schemas import (
    AgeBand,
    ChildAttendance,
    DiaryEntry,
    DiaryEvaluation,
    IndividualNote,
    ThreeViewpoint,
)


def _entry() -> DiaryEntry:
    return DiaryEntry(
        date=date(2026, 6, 25),
        age_band=AgeBand.零から二歳,
        weather="晴れ",
        attendance=[
            ChildAttendance(child_id="架空児A", present=True),
            ChildAttendance(child_id="架空児B", present=False, reason="発熱"),
        ],
        practice_record="園庭で砂遊び",
        individual_notes=[
            IndividualNote(
                child_id="架空児A",
                observed_state="砂の感触を確かめた",
                tags=[ThreeViewpoint.身近なものと関わり感性が育つ],
            )
        ],
        evaluation=DiaryEvaluation(child_focus="感触に集中", self_review="道具が適切"),
        parent_contact="日中は元気でした",
    )


def test_write_draft_contains_core_sections():
    text = write_draft(_entry())
    for marker in ["保育の実践記録", "個別の記録", "評価・反省", "保護者への連絡"]:
        assert marker in text


def test_write_draft_emits_explicit_tag():
    """タグ（3つの視点）が明示出力される（§13 の差別化）。"""
    assert "身近なものと関わり感性が育つ" in write_draft(_entry())


def test_write_draft_summarizes_attendance():
    text = write_draft(_entry())
    assert "出席 1名" in text
    assert "架空児B" in text and "発熱" in text


def test_write_draft_template_ref_noted():
    assert "様式X" in write_draft(_entry(), template_ref="様式X")
