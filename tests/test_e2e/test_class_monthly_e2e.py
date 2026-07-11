"""決定論E2E（結合テスト）：クラス月案パイプライン＋doc_type 分岐ルータ＋集積還流を LLM 非依存に通す。

設計コンテキスト §3/§4 / §10 / §18（園の実様式）/ §16 / 依存モデル（2026-07 確定）。個別月案の
test_monthly_e2e と対称に、クラス月案パス（園の実様式・区分×領域グリッド＋0–2 の個人目標）を実 ADK
ランタイムで end-to-end に回す（creds 不要・無料・決定的）。担保する結合経路:
  1. ルータ分岐   doc_type=="クラス月案" → class_monthly_pipeline
  2. 集積還流     author が3系統の候補を fetch_reference で選択取得（未反映境界は harness）
                 ＋評価・反省（class_diary_reflections・決定B）
  3. 確定         class_monthly finalize が ClassMonthlyPlan を復元→検査→整形（final_document）
  4. 年齢分岐     0–2 は個人目標必須／3–5 は不要（園フォームに 0–2 だけ個人目標小表がある）
  5. 正準化       author が grid の行を欠いても model_validator が正準7行にそろえて確定が通る
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
from hoiku_agent.schemas import GRID_ROWS  # noqa: E402

_APP = "hoiku_class_monthly_e2e"
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


def _prev_entry(child: str, day: int) -> dict:
    """前月日誌（実在しない仮名・0–2 個別）の dict。L2 還流の入力（クラス＝複数児）。"""
    return {
        "date": f"2026-06-{day:02d}",
        "age_band": "0-2",
        "weather": "晴れ",
        "attendance": [{"child_id": child, "present": True, "reason": None}],
        "practice_record": "園庭で感触遊びを行った。",
        "individual_notes": [
            {
                "child_id": child,
                "observed_state": f"6月{day}日：{child}は砂をすくって感触を確かめた",
                "tags": ["身近なものと関わり感性が育つ"],
            }
        ],
        "evaluation": {"child_focus": "感触に集中していた", "self_review": "素材を十分用意できた"},
    }


def _child_record(child: str, period: str) -> dict:
    """クラス児童の保育経過記録（実在しない仮名・依存モデル①）の dict。"""
    return {
        "period": period,
        "age_band": "0-2",
        "child_id": child,
        "development_notes": [
            {
                "description": f"{child}は{period}に感触遊びへ意欲的に関わった",
                "tags": ["身近なものと関わり感性が育つ"],
            }
        ],
        "care_notes": "",
        "family_liaison": "",
        "overall_note": f"{period}を通じて探索意欲が育った",
        "next_aims": "手指を使う遊びを広げる",
    }


def _past_plan(month: str) -> dict:
    """それまでのクラス月案（依存モデル②）の dict。"""
    return {
        "month": month,
        "age_band": "0-2",
        "monthly_goal": f"{month} の保育目標",
        "prev_month_state": "先月の姿",
        "grid": [{"category": "教育", "domain": "健康", "aim": "戸外で体を動かす"}],
        "teacher_evaluation": "水遊びで発散できた",
    }


def _full_grid() -> list[dict]:
    """正準7行ぶんのグリッド（各欄を埋めた happy path）。"""
    return [
        {
            "category": category,
            "domain": domain,
            "aim": f"{domain}のねらい",
            "environment": "環境・構成",
            "child_state": "子どもの姿",
            "support": "援助・配慮",
        }
        for category, domain in GRID_ROWS
    ]


def _class_plan(age_band: str, *, grid: list[dict] | None = None, goals: list[dict] | None) -> dict:
    plan = {
        "month": "2026-07",
        "age_band": age_band,
        "class_name": "ひよこ組",
        "monthly_goal": "梅雨期も健康に過ごし、感触遊びを楽しむ",
        "prev_month_state": "前月は砂遊びに繰り返し関わり感触を楽しむ姿が増えた",
        "events": "七夕の集い",
        "parent_support": "体調変化を連絡帳で共有する",
        "grid": grid if grid is not None else _full_grid(),
        "syokuiku": "手づかみ食べを見守る",
        "health_safety": "午睡時のブレスチェック",
        "family_liaison": "連絡帳で連携する",
        "staff_liaison": "体調児を申し送る",
        "individual_goals": goals if goals is not None else [],
    }
    return plan


def _class_author_text(plan: dict) -> str:
    return (
        "前月集積からクラス月案の下書きを作成しました。\n```json\n"
        + json.dumps(plan, ensure_ascii=False, indent=2)
        + "\n```"
    )


def _run(author_model, reviewer_model, initial_state: dict, session_id: str = "cm1"):
    async def _go():
        root = build_root_agent(author_model=author_model, reviewer_model=reviewer_model)
        session_service = InMemorySessionService()
        await session_service.create_session(
            app_name=_APP, user_id=_USER, session_id=session_id, state=initial_state
        )
        runner = Runner(app_name=_APP, agent=root, session_service=session_service)
        _events = [
            ev
            async for ev in runner.run_async(
                user_id=_USER,
                session_id=session_id,
                new_message=types.Content(
                    role="user", parts=[types.Part(text="7月のクラス月案を作成してください。")]
                ),
            )
        ]
        sess = await session_service.get_session(
            app_name=_APP, user_id=_USER, session_id=session_id
        )
        return dict(sess.state), _events

    return asyncio.run(_go())


def test_class_monthly_path_aggregates_inputs_and_finalizes():
    """① ルータ分岐（クラス月案）＋② 3系統の集積還流（経過記録・自己履歴・未反映日誌）＋③ 確定（0–2・個人目標）。"""
    goals = [
        {"child_id": "はるとくん", "child_state": "歩行が安定", "aim_support": "探索を保障する"},
        {"child_id": "ゆいちゃん", "child_state": "感触遊びを好む", "aim_support": "素材を増やす"},
    ]
    author = FakeLlm(responses=[_class_author_text(_class_plan("0-2", goals=goals))])
    reviewer = FakeLlm(responses=["APPROVED\n指摘なし。"])
    state = {
        "doc_type": "クラス月案",
        # ① クラス児童の保育経過記録（〜5月末をカバー＝6月の日誌が「未反映」になる境界）
        "class_record_entries": [
            _child_record("はるとくん", "2026-03〜2026-05"),
            _child_record("ゆいちゃん", "2026-03〜2026-05"),
        ],
        # ② それまでのクラス月案
        "past_class_plans": [_past_plan("2026-06"), _past_plan("2026-05")],
        # ③ 日誌（5月分＝経過記録に反映済み・6月分＝未反映）
        "class_diary_entries": [
            _prev_entry("はるとくん", 12),
            _prev_entry("ゆいちゃん", 13),
            _prev_entry("はるとくん", 26),
            {**_prev_entry("はるとくん", 12), "date": "2026-05-20"},  # 反映済み＝集計から除外される
        ],
    }

    final_state, _ = _run(author, reviewer, state)

    # ②-1 クラス児童の保育経過記録が child_id 別に集計され state に乗る
    assert "class_records_digest" not in final_state
    assert "class_plan_digest" not in final_state
    assert "class_diary_digest" not in final_state
    # ③ 確定：ClassMonthlyPlan が復元・検査通過・園様式で整形される
    assert final_state.get("finalize_parse_error") is None
    assert final_state.get("validation") == []
    doc = final_state.get("final_document") or ""
    assert "月間指導計画" in doc and "個人目標" in doc
    assert final_state.get("final_doc_kind") == "class_monthly"
    assert final_state.get("awaiting_caregiver_approval") is True
    # 個人目標が登場児ぶん確定 entry に残る
    entry = final_state.get("final_entry") or {}
    assert {g["child_id"] for g in entry.get("individual_goals") or []} == {
        "はるとくん",
        "ゆいちゃん",
    }
    # grid は正準7行にそろう
    assert [r["domain"] for r in entry.get("grid") or []] == [d for _c, d in GRID_ROWS]
    assert author.call_count == 1


def test_class_monthly_3_5_needs_no_individual_goals():
    """3–5 クラスは個人目標が無くても確定する（園フォームに 0–2 だけ個人目標小表がある＝§18）。"""
    author = FakeLlm(responses=[_class_author_text(_class_plan("3-5", goals=[]))])
    reviewer = FakeLlm(responses=["APPROVED\n指摘なし。"])
    state = {"doc_type": "クラス月案", "class_diary_entries": [_prev_entry("さくらちゃん", 20)]}

    final_state, _ = _run(author, reviewer, state, session_id="cm35")

    assert final_state.get("finalize_parse_error") is None
    assert final_state.get("validation") == []
    assert final_state.get("final_doc_kind") == "class_monthly"


def test_class_monthly_grid_canonicalized_from_partial():
    """author が grid の行を欠いても model_validator が正準7行にそろえ、確定が通る（型の保証・§18）。"""
    # 養護2行＋教育1行（健康）だけ＝残り4領域は欠落。正準化で空行が補完され7行になるが、
    # 空行のねらいは validate が「未記入」で報告する（型成立だが中身不足＝正しい可視化）。
    partial = [
        {"category": "養護", "domain": "生命の保持", "aim": "快適に過ごす"},
        {"category": "養護", "domain": "情緒の安定", "aim": "安心して過ごす"},
        {"category": "教育", "domain": "健康", "aim": "水や砂に親しむ"},
    ]
    goals = [{"child_id": "はるとくん", "child_state": "歩行安定", "aim_support": "探索保障"}]
    author = FakeLlm(responses=[_class_author_text(_class_plan("0-2", grid=partial, goals=goals))])
    # 巡回上限まで同じ下書きを返す（未充足でも上限で finalize へ抜ける）。
    reviewer = FakeLlm(responses=["NEEDS_REVISION\n領域のねらいを補ってください。"])
    state = {"doc_type": "クラス月案", "class_diary_entries": [_prev_entry("はるとくん", 12)]}

    final_state, _ = _run(author, reviewer, state, session_id="cmgrid")

    entry = final_state.get("final_entry") or {}
    # 正準7行にそろう（欠落領域は空行で補完）
    assert [r["domain"] for r in entry.get("grid") or []] == [d for _c, d in GRID_ROWS]
    # 欠落領域のねらい未記入が validation で正直に報告される（型成立・中身不足の可視化）
    problems = final_state.get("validation") or []
    assert any("表現" in p and "ねらい" in p for p in problems)
