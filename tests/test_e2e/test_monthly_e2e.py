"""決定論E2E（結合テスト）：月案パイプライン＋doc_type 分岐ルータ＋L2 還流を LLM 非依存に通す。

設計コンテキスト §3/§4（L2 月次PDCA）/ §10（月⇄日集積）/ §16。日誌の test_pipeline_e2e と対称に、
月案パスを実 ADK ランタイムで end-to-end に回す（creds 不要・無料・決定的）。担保する結合経路:
  1. ルータ分岐   doc_type=="月案" → monthly_plan_pipeline / 未設定 → document_pipeline（既定 日誌）
  2. L2 還流      前月日誌（state["prev_month_entries"]）→ monthly_prep が child_id 別集計
                  → state["prev_month_digest"]（要約は author・集計は harness）
  3. 確定         monthly finalize が MonthlyPlan を復元→検査→整形（final_document）
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

_APP = "hoiku_monthly_e2e"
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


def _prev_entry(day: int) -> dict:
    """前月日誌（架空児A・0–2 個別）の dict。L2 還流の入力。"""
    return {
        "date": f"2026-06-{day:02d}",
        "age_band": "0-2",
        "weather": "晴れ",
        "attendance": [{"child_id": "架空児A", "present": True, "reason": None}],
        "practice_record": "園庭で感触遊びを行った。",
        "individual_notes": [
            {
                "child_id": "架空児A",
                "observed_state": f"6月{day}日：砂をすくって感触を確かめた",
                "tags": ["身近なものと関わり感性が育つ"],
            }
        ],
        "evaluation": {"child_focus": "感触に集中していた", "self_review": "素材を十分用意できた"},
    }


def _monthly_plan() -> dict:
    return {
        "month": "2026-07",
        "age_band": "0-2",
        "child_id": "架空児A",
        "prev_child_state": "前月は砂遊びに繰り返し関わり感触を楽しんだ",
        "nurturing": "情緒の安定を図り安心して過ごせるようにする",
        "education": [
            {"aim": "身近な素材に触れ感覚を働かせる", "tags": ["身近なものと関わり感性が育つ"]}
        ],
        "monthly_goals": "感触遊びを広げ、表現の芽を育てる",
        "environment_support": "複数の素材を用意し落ち着いて関われる場を作る",
        "events_family_food": None,
        "evaluation_reflection": "予想したねらいに対し実際の姿はおおむね沿っていた",
    }


def _monthly_author_text(plan: dict) -> str:
    return (
        "前月集積から月案の下書きを作成しました。\n```json\n"
        + json.dumps(plan, ensure_ascii=False, indent=2)
        + "\n```"
    )


def _run(author_model, reviewer_model, initial_state: dict, session_id: str = "m1"):
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
                    role="user", parts=[types.Part(text="7月の個別月案を作成してください。")]
                ),
            )
        ]
        sess = await session_service.get_session(
            app_name=_APP, user_id=_USER, session_id=session_id
        )
        return dict(sess.state), events

    return asyncio.run(_go())


def test_monthly_path_aggregates_prev_month_and_finalizes():
    """① ルータ分岐（月案）＋② L2 還流（前月集計）＋③ 月案確定。"""
    author = FakeLlm(responses=[_monthly_author_text(_monthly_plan())])
    reviewer = FakeLlm(responses=["APPROVED\n指摘なし。"])
    state = {
        "doc_type": "月案",
        "prev_month_entries": [_prev_entry(25), _prev_entry(26)],
    }

    final_state, _ = _run(author, reviewer, state)

    # ② L2 還流：前月日誌が child_id 別に決定的集計され state に乗る
    digest = final_state.get("prev_month_digest") or {}
    assert "架空児A" in digest
    assert digest["架空児A"]["note_count"] == 2
    # ③ 確定：MonthlyPlan が復元・検査通過・月案様式で整形される
    assert final_state.get("finalize_parse_error") is None
    assert final_state.get("validation") == []
    assert "前月の子どもの姿" in (final_state.get("final_document") or "")
    assert final_state.get("awaiting_caregiver_approval") is True
    # ① 月案 author が呼ばれた（日誌 author ではない）
    assert author.call_count == 1


def test_monthly_prep_degrades_without_prev_entries():
    """前月日誌が無くても（初月）空 digest で素通りし月案は作れる（降格・落ちない）。"""
    author = FakeLlm(responses=[_monthly_author_text(_monthly_plan())])
    reviewer = FakeLlm(responses=["APPROVED\n指摘なし。"])

    final_state, _ = _run(author, reviewer, {"doc_type": "月案"})

    assert final_state.get("prev_month_digest") == {}
    assert final_state.get("final_document")  # 初月でも月案は確定下書きまで作る


def test_router_defaults_to_diary_when_doc_type_unset():
    """doc_type 未設定なら既定で日誌パイプライン（既存デモ挙動が不変＝§3 日誌先行）。"""
    diary_entry = {
        "date": "2026-07-01",
        "age_band": "0-2",
        "weather": "晴れ",
        "attendance": [{"child_id": "架空児A", "present": True, "reason": None}],
        "practice_record": "散歩に出かけた。",
        "individual_notes": [
            {
                "child_id": "架空児A",
                "observed_state": "花を見つめた",
                "tags": ["健やかに伸び伸び育つ"],
            }
        ],
        "evaluation": {"child_focus": "興味を示した", "self_review": "環境は適切だった"},
    }
    author = FakeLlm(
        responses=[
            "日誌の下書きです。\n```json\n" + json.dumps(diary_entry, ensure_ascii=False) + "\n```"
        ]
    )
    reviewer = FakeLlm(responses=["APPROVED\n指摘なし。"])

    final_state, _ = _run(author, reviewer, {})  # doc_type 未設定

    # 日誌パスを通った（月案集積は走らない・日誌様式で確定）
    assert final_state.get("prev_month_digest") is None
    assert "保育日誌" in (final_state.get("final_document") or "")
