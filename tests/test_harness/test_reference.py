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


def test_plain_string_source_is_coerced_like_adk_tool_args():
    """ADK の FunctionTool は引数を素の str で渡す＝eval/本番の実呼び出し経路（CI 赤の回帰防止）。"""
    state = {}
    result = fetch_reference_from_state(state, "period_diary")
    assert result["source"] == "period_diary"
    assert result["empty"] is True
    assert state["reference_manifest"] == [{"source": "period_diary", "count": 0, "empty": True}]


def test_fetch_class_roster_lists_members_and_records_manifest():
    """在籍児名簿（クラス・園児マスタ）＝dict 列をそのまま列挙（0–2 個人目標の対象の与件）。"""
    state = {
        "class_roster": [
            {"child_id": "はるとくん", "age_months": "1歳3か月", "class_name": "ひよこ組"},
            {"child_id": "", "age_months": "", "class_name": ""},  # 呼び名空の行は数えない
        ]
    }
    result = fetch_reference_from_state(state, ReferenceSource.class_roster)
    assert result["count"] == 1
    assert result["empty"] is False
    assert "はるとくん" in result["content"]
    assert "1歳3か月" in result["content"]
    assert state["reference_manifest"] == [{"source": "class_roster", "count": 1, "empty": False}]


def test_fetch_class_roster_empty_returns_honest_message():
    """名簿未整備は「登録されていません」を返し、author が記録の登場児での作成へ降格できる。"""
    result = fetch_reference_from_state({}, ReferenceSource.class_roster)
    assert result["empty"] is True
    assert "在籍児が登録されていません" in result["content"]


def test_unknown_source_degrades_honestly_without_raising():
    state = {}
    result = fetch_reference_from_state(state, "unknown_source")
    assert result["empty"] is True
    assert "有効な参照種別" in result["content"]
    assert "period_diary" in result["content"]
    assert "reference_manifest" not in state
