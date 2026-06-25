"""harness.aggregate_by_child の単体テスト（LLM 非依存・高速）。

設計コンテキスト §16：月⇔日の決定的集計は pytest で必須。
"""

from __future__ import annotations

from datetime import date

from hoiku_agent.harness import aggregate_by_child, format_digest_for_prompt, prev_month_digest
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


def test_prev_month_digest_is_json_serializable():
    """state へ載せる L2 還流の digest は素の dict（Counter でない）で JSON 化できる。"""
    import json

    digest = prev_month_digest([_entry(1, "c001"), _entry(2, "c001")])
    assert digest["c001"]["note_count"] == 2
    # tag_freq は素の dict（Counter は不可）。json.dumps が通る＝state/Memory に載せられる。
    assert isinstance(digest["c001"]["tag_freq"], dict)
    json.dumps(digest, ensure_ascii=False)
    assert digest["c001"]["tag_freq"]["身近な人と気持ちが通じ合う"] == 2


def test_format_digest_lists_facts_without_summarizing():
    """整形テキストは child_id・件数・観察文を列挙する（要約は author の責務＝集計のみ）。"""
    text = format_digest_for_prompt(prev_month_digest([_entry(1, "c001"), _entry(2, "c001")]))
    assert "c001" in text
    assert "1日の姿" in text and "2日の姿" in text


def test_format_digest_empty_degrades():
    """前月データ無し（初月/未提供）でも空 digest で降格メッセージを返す（落ちない）。"""
    text = format_digest_for_prompt(prev_month_digest([]))
    assert "前月の日誌データがありません" in text
