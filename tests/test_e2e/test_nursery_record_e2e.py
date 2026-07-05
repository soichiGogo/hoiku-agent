"""決定論E2E（結合テスト）：保育要録パイプライン＋doc_type 分岐＋L4 還流を LLM 非依存に通す。

設計コンテキスト §19（保育要録＝集積階層の最終段 L4＝最終年度の児童票を集積）/ §16。児童票の
test_child_record_e2e と対称に、要録パスを実 ADK ランタイムで end-to-end に回す（creds 不要・無料・
決定的）。担保する結合経路:
  1. ルータ分岐   doc_type=="保育要録" → nursery_record_pipeline
  2. L4 還流      最終年度の児童票（state["record_entries"]）→ record_prep が child_id 別集計
                  → state["record_digest"]（要約は author・集計は harness）
  3. 確定         nursery_record finalize が NurseryRecord を復元→検査→整形（final_document /
                  final_doc_kind="nursery_record"）
  4. 降格         最終年度の児童票が無くても空 digest で素通りし要録は作れる（落ちない）
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

_APP = "hoiku_nursery_record_e2e"
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


def _child_record(period: str, domain_tag: str, desc: str) -> dict:
    """最終年度（年長=3–5）の児童票（架空児A）の dict。L4 還流の入力。"""
    return {
        "period": period,
        "age_band": "3-5",
        "child_id": "架空児A",
        "development_notes": [{"description": desc, "tags": [domain_tag]}],
        "care_notes": "",
        "family_liaison": "",
        "overall_note": f"{period}：友だちとの関わりを広げながら意欲的に活動した",
        "next_aims": "",
    }


def _nursery_record() -> dict:
    return {
        "fiscal_year": "2026",
        "age_band": "3-5",
        "child_id": "架空児A",
        "final_year_focus": "共通の目的に向かって思いや考えを出し合いながら活動を楽しむ",
        "individual_focus": "自分を発揮しながらさまざまな活動を楽しむ",
        "development_notes": [
            {"description": "運動遊びに繰り返し挑戦し、できた喜びを味わった", "tags": ["健康"]},
            {"description": "友だちと考えを出し合い協力する姿が増えた", "tags": ["人間関係"]},
        ],
        "special_notes": "",
        "growth_until_final": "入園当初は不安が大きかったが、生活のリズムが身につき生き生きと表現を楽しむ姿へ育った",
    }


def _author_text(record: dict) -> str:
    return (
        "最終年度の児童票集積から保育要録の下書きを作成しました。\n```json\n"
        + json.dumps(record, ensure_ascii=False, indent=2)
        + "\n```"
    )


def _run(author_model, reviewer_model, initial_state: dict, session_id: str = "y1"):
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
                    parts=[types.Part(text="2026年度の保育要録を作成してください。")],
                ),
            )
        ]
        sess = await session_service.get_session(
            app_name=_APP, user_id=_USER, session_id=session_id
        )
        return dict(sess.state), events

    return asyncio.run(_go())


def test_nursery_record_path_aggregates_final_year_and_finalizes():
    """① ルータ分岐（保育要録）＋② L4 還流（最終年度の児童票集計）＋③ 要録確定。"""
    author = FakeLlm(responses=[_author_text(_nursery_record())])
    reviewer = FakeLlm(responses=["APPROVED\n指摘なし。"])
    state = {
        "doc_type": "保育要録",
        "record_entries": [
            _child_record("2026-04〜2026-06", "健康", "運動遊びに親しんだ"),
            _child_record("2026-07〜2026-09", "人間関係", "友だちとの関わりが増えた"),
            _child_record("2026-10〜2026-12", "表現", "劇遊びで役になりきった"),
        ],
    }

    final_state, events = _run(author, reviewer, state)

    # ② L4 還流：最終年度の児童票が child_id 別に決定的集計され state に乗る
    digest = final_state.get("record_digest") or {}
    assert "架空児A" in digest
    assert digest["架空児A"]["record_count"] == 3
    assert len(digest["架空児A"]["periods"]) == 3
    # 月案・児童票の digest キーは汚さない（集計対象の分離）
    assert final_state.get("prev_month_digest") is None
    assert final_state.get("period_digest") is None
    # ③ 確定：NurseryRecord が復元・検査通過・要録様式で整形される
    assert final_state.get("finalize_parse_error") is None
    assert final_state.get("validation") == []
    assert "保育所児童保育要録" in (final_state.get("final_document") or "")
    assert final_state.get("final_doc_kind") == "nursery_record"
    assert final_state.get("awaiting_caregiver_approval") is True
    # ① 要録 author が呼ばれた
    assert author.call_count == 1
    # custom BaseAgent（record_prep 等）が invocation_id を伝播している（ADK eval 整合の回帰防止）
    assert all(ev.invocation_id for ev in events)


def test_record_prep_degrades_without_entries():
    """最終年度の児童票が無くても空 digest で素通りし要録は作れる（降格・落ちない）。"""
    author = FakeLlm(responses=[_author_text(_nursery_record())])
    reviewer = FakeLlm(responses=["APPROVED\n指摘なし。"])

    final_state, _ = _run(author, reviewer, {"doc_type": "保育要録"})

    assert final_state.get("record_digest") == {}
    assert final_state.get("final_document")  # 初回でも要録は確定下書きまで作る
