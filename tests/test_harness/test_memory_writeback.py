"""承認版→子ども別Memory factの決定ロジック（LLM/GCP非依存）。"""

from __future__ import annotations

import asyncio

import pytest

from hoiku_agent.harness.memory_writeback import approved_memory_facts, persist_approved_facts


def _diary_entry() -> dict:
    return {
        "date": "2026-07-11",
        "age_band": "0-2",
        "weather": "晴れ",
        "attendance": [{"child_id": "架空児A", "present": True}],
        "individual_notes": [
            {
                "child_id": "架空児A",
                "observed_state": "砂を指先で確かめ、繰り返し容器へ移した。",
                "tags": ["身近なものと関わり感性が育つ"],
                "life_record": {"meal": "完食", "sleep": "12:30〜14:30"},
                "individual_aim": "砂の感触を十分に味わう。",
            }
        ],
        "evaluation": {"child_focus": "探索が続いた。", "self_review": "容器を増やした。"},
    }


def test_diary_fact_contains_observation_but_not_future_aim() -> None:
    facts = approved_memory_facts("diary", _diary_entry())
    assert len(facts) == 1 and facts[0].child_id == "架空児A"
    assert "砂を指先で確かめ" in facts[0].text
    assert "完食" in facts[0].text
    assert "砂の感触を十分に味わう" not in facts[0].text


def test_class_monthly_without_child_facts_is_not_applicable() -> None:
    entry = {
        "month": "2026-07",
        "age_band": "3-5",
        "monthly_goal": "友だちと遊びをつくる。",
        "prev_month_state": "クラス全体でルールを相談する姿があった。",
        "grid": [],
        "individual_goals": [],
    }
    assert approved_memory_facts("class_monthly", entry) == []


@pytest.mark.parametrize(
    ("kind", "entry", "expected"),
    [
        (
            "monthly",
            {
                "month": "2026-07",
                "age_band": "0-2",
                "child_id": "架空児A",
                "prev_child_state": "水に手を伸ばし、感触を確かめていた。",
                "nurturing_life": "休息を取れるようにする。",
                "nurturing_emotion": "安心して試せるようにする。",
                "education": [],
                "monthly_goals": "水の感触を味わう。",
                "environment_support": "容器を用意する。",
                "evaluation_reflection": "自分から繰り返し水へ触れた。",
            },
            "自分から繰り返し水へ触れた",
        ),
        (
            "child_record",
            {
                "period": "2026-04〜2026-06",
                "age_band": "0-2",
                "child_id": "架空児A",
                "development_notes": [{"description": "素材への探索が広がった。"}],
                "overall_note": "自分から関わる姿が増えた。",
            },
            "素材への探索が広がった",
        ),
        (
            "nursery_record",
            {
                "fiscal_year": "2026",
                "age_band": "3-5",
                "child_id": "架空児A",
                "final_year_focus": "協同する経験を重ねる。",
                "individual_focus": "思いを言葉で伝える。",
                "development_notes": [{"description": "友だちと役割を相談した。"}],
                "growth_until_final": "遊びの中で相手の思いに気づく姿が育った。",
            },
            "友だちと役割を相談した",
        ),
    ],
)
def test_personal_documents_extract_observed_history(kind: str, entry: dict, expected: str) -> None:
    facts = approved_memory_facts(kind, entry)
    assert len(facts) == 1 and facts[0].child_id == "架空児A"
    assert expected in facts[0].text


class _SpyMemory:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def add_memory(self, **kwargs) -> None:
        self.calls.append(kwargs)


def test_persist_waits_for_consolidated_memory_generation() -> None:
    memory = _SpyMemory()
    facts = approved_memory_facts("diary", _diary_entry())
    asyncio.run(
        persist_approved_facts(
            memory,  # type: ignore[arg-type]
            app_name="hoiku_agent",
            user_id="workspace:test",
            source_version_id="version-1",
            facts=facts,
        )
    )
    assert len(memory.calls) == 1
    call = memory.calls[0]
    assert call["custom_metadata"]["enable_consolidation"] is True
    assert call["custom_metadata"]["wait_for_completion"] is True
    assert "承認版ID=version-1" in call["memories"][0].content.parts[0].text
