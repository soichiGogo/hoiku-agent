"""決定論E2E（結合テスト）：保育経過記録パイプライン＋doc_type 分岐＋L3 還流を LLM 非依存に通す。

設計コンテキスト §19（保育経過記録（期ごと）・L3 集積）/ §16。月案の test_monthly_e2e と
対称に、保育経過記録パスを実 ADK ランタイムで end-to-end に回す（creds 不要・無料・決定的）。担保する結合経路:
  1. ルータ分岐   doc_type=="保育経過記録" → child_record_pipeline
  2. L3 還流      期間中の日誌（state["period_entries"]）→ period_prep が child_id 別集計
                  → state["period_digest"]（要約は author・集計は harness）
  3. 確定         child_record finalize が ChildRecord を復元→検査→整形（final_document /
                  final_doc_kind="child_record"）
  4. 降格         期間日誌が無くても空 digest で素通りし保育経過記録は作れる（落ちない）
"""

from __future__ import annotations

import asyncio
import json

import pytest

pytest.importorskip("google.adk", reason="google-adk 未インストール（uv sync 後に有効化）")

from typing import AsyncGenerator  # noqa: E402

from google.adk.models import BaseLlm, LlmResponse  # noqa: E402
from google.adk.runners import Runner  # noqa: E402
from google.adk.sessions import InMemorySessionService  # noqa: E402
from google.genai import types  # noqa: E402
from pydantic import PrivateAttr  # noqa: E402

from hoiku_agent.harness import build_root_agent  # noqa: E402

_APP = "hoiku_child_record_e2e"
_USER = "tester"


class FakeLlm(BaseLlm):
    """決定論E2E 用の LLM スタブ（テスト専用・creds 不要）。responses[i] を i 回目に返す。"""

    model: str = "fake-llm"
    responses: list[str]
    _calls: int = PrivateAttr(default=0)

    @property
    def call_count(self) -> int:
        return self._calls

    async def generate_content_async(
        self, llm_request, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        idx = min(self._calls, len(self.responses) - 1)
        self._calls += 1
        yield LlmResponse(
            content=types.Content(role="model", parts=[types.Part(text=self.responses[idx])])
        )


def _period_entry(month: int, day: int) -> dict:
    """期間中の日誌（架空児A・0–2 個別）の dict。L3 還流の入力。"""
    return {
        "date": f"2026-{month:02d}-{day:02d}",
        "age_band": "0-2",
        "weather": "晴れ",
        "attendance": [{"child_id": "架空児A", "present": True, "reason": None}],
        "practice_record": "園庭で感触遊びを行った。",
        "individual_notes": [
            {
                "child_id": "架空児A",
                "observed_state": f"{month}月{day}日：砂をすくって感触を確かめた",
                "tags": ["身近なものと関わり感性が育つ"],
            }
        ],
        "evaluation": {"child_focus": "感触に集中していた", "self_review": "素材を十分用意できた"},
    }


def _child_record() -> dict:
    return {
        "period": "2026-04〜2026-06",
        "age_band": "0-2",
        "child_id": "架空児A",
        "development_notes": [
            {
                "description": "感触遊びに繰り返し関わり、素材への探索が広がった",
                "tags": ["身近なものと関わり感性が育つ"],
            }
        ],
        "care_notes": "",
        "family_liaison": "",
        "overall_note": "身近なものへの興味を土台に、自分から関わる姿が育った",
        "next_aims": "",
    }


def _author_text(record: dict) -> str:
    return (
        "期間集積から保育経過記録の下書きを作成しました。\n```json\n"
        + json.dumps(record, ensure_ascii=False, indent=2)
        + "\n```"
    )


def _run(author_model, reviewer_model, initial_state: dict, session_id: str = "c1"):
    async def _go():
        root = build_root_agent(author_model=author_model, reviewer_model=reviewer_model)
        session_service = InMemorySessionService()
        await session_service.create_session(
            app_name=_APP, user_id=_USER, session_id=session_id, state=initial_state
        )
        runner = Runner(app_name=_APP, agent=root, session_service=session_service)
        events = [
            ev
            async for ev in runner.run_async(
                user_id=_USER,
                session_id=session_id,
                new_message=types.Content(
                    role="user",
                    parts=[types.Part(text="2026-04〜2026-06 の保育経過記録を作成してください。")],
                ),
            )
        ]
        sess = await session_service.get_session(
            app_name=_APP, user_id=_USER, session_id=session_id
        )
        return dict(sess.state), events

    return asyncio.run(_go())


def test_child_record_path_aggregates_period_and_finalizes():
    """① ルータ分岐（保育経過記録）＋② L3 還流（期間集計）＋③ 保育経過記録確定。"""
    author = FakeLlm(responses=[_author_text(_child_record())])
    reviewer = FakeLlm(responses=["APPROVED\n指摘なし。"])
    state = {
        "doc_type": "保育経過記録",
        "period_entries": [_period_entry(4, 10), _period_entry(5, 15), _period_entry(6, 12)],
    }

    final_state, events = _run(author, reviewer, state)

    # ② L3 還流：期間中の日誌が child_id 別に決定的集計され state に乗る
    digest = final_state.get("period_digest") or {}
    assert "架空児A" in digest
    assert digest["架空児A"]["note_count"] == 3
    # 月案の digest キーは汚さない（キー一般化の分離）
    assert final_state.get("prev_month_digest") is None
    # ③ 確定：ChildRecord が復元・検査通過・保育経過記録様式で整形される
    assert final_state.get("finalize_parse_error") is None
    assert final_state.get("validation") == []
    assert "保育経過記録" in (final_state.get("final_document") or "")
    assert final_state.get("final_doc_kind") == "child_record"
    assert final_state.get("awaiting_caregiver_approval") is True
    # ① 保育経過記録 author が呼ばれた
    assert author.call_count == 1
    # custom BaseAgent（period_prep 等）が invocation_id を伝播している（ADK eval 整合の回帰防止）
    assert all(ev.invocation_id for ev in events)


def test_period_prep_degrades_without_entries():
    """期間日誌が無くても（初回）空 digest で素通りし保育経過記録は作れる（降格・落ちない）。"""
    author = FakeLlm(responses=[_author_text(_child_record())])
    reviewer = FakeLlm(responses=["APPROVED\n指摘なし。"])

    final_state, _ = _run(author, reviewer, {"doc_type": "保育経過記録"})

    assert final_state.get("period_digest") == {}
    assert final_state.get("final_document")  # 初回でも保育経過記録は確定下書きまで作る
