"""harness.validate_fields の単体テスト（LLM 非依存・高速）。

設計コンテキスト §16：LLM 非依存の決定的ロジック（年齢分岐・必須欄）は pytest で必須。
"""

from __future__ import annotations

from datetime import date

from hoiku_agent.harness import validate_fields
from hoiku_agent.schemas import (
    AgeBand,
    ChildAttendance,
    DiaryEntry,
    DiaryEvaluation,
    FiveDomains,
    IndividualNote,
    TenNoSugata,
    ThreeViewpoint,
)


def _entry(
    *,
    age_band: AgeBand = AgeBand.零から二歳,
    tags: list | None = None,
    weather: str = "晴れ",
    practice_record: str = "散歩で草花に触れた",
    observed_state: str = "花を見つめた",
    child_focus: str = "興味を示した",
    self_review: str = "環境構成は適切だった",
    individual_notes: list | None = None,
) -> DiaryEntry:
    if individual_notes is None:
        individual_notes = [
            IndividualNote(
                child_id="架空児A",
                observed_state=observed_state,
                tags=tags if tags is not None else [ThreeViewpoint.健やかに伸び伸びと育つ],
            )
        ]
    return DiaryEntry(
        date=date(2026, 6, 25),
        age_band=age_band,
        weather=weather,
        attendance=[ChildAttendance(child_id="架空児A", present=True)],
        practice_record=practice_record,
        individual_notes=individual_notes,
        evaluation=DiaryEvaluation(child_focus=child_focus, self_review=self_review),
    )


def test_valid_0_2_entry_passes():
    assert validate_fields(_entry()) == []


def test_0_2_requires_three_viewpoint_tag():
    """0–2歳で3つの視点タグが無い個別記録は違反になる。"""
    assert any("3つの視点" in p for p in validate_fields(_entry(tags=[])))


def test_0_2_with_only_ten_no_sugata_is_insufficient():
    """0–2 で10の姿だけ・3つの視点なしは違反。"""
    assert any("3つの視点" in p for p in validate_fields(_entry(tags=[TenNoSugata.健康な心と体])))


def test_3_5_requires_five_domains_tag():
    """3–5 は5領域タグが必須（3つの視点だけでは違反）。"""
    problems = validate_fields(
        _entry(age_band=AgeBand.三から五歳, tags=[ThreeViewpoint.健やかに伸び伸びと育つ])
    )
    assert any("5領域" in p for p in problems)


def test_3_5_with_five_domains_passes():
    assert validate_fields(_entry(age_band=AgeBand.三から五歳, tags=[FiveDomains.言葉])) == []


def test_missing_weather_is_violation():
    assert any("天候" in p for p in validate_fields(_entry(weather="  ")))


def test_missing_practice_record_is_violation():
    assert any("実践記録" in p for p in validate_fields(_entry(practice_record="")))


def test_empty_individual_notes_is_violation():
    assert any("個別日誌" in p for p in validate_fields(_entry(individual_notes=[])))


def test_blank_evaluation_views_are_violations():
    problems = validate_fields(_entry(child_focus="", self_review="   "))
    assert sum(1 for p in problems if "評価・反省" in p) == 2


def test_blank_observed_state_is_violation():
    assert any("子どもの姿" in p for p in validate_fields(_entry(observed_state="")))
