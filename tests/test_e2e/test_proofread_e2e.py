"""決定論E2E（結合テスト）：校正AI（日本語チェック・言い換え提案）を LLM 非依存に通す。

設計コンテキスト §11 / §16。校正AI（`agents/proofreader_agent`）を InMemoryRunner で1パス駆動する
`web/proofread.proofread_entry` に FakeLlm を注入し、抽出→提案→**パスへの写像・フィルタ**という結合を
creds 不要・決定的に検証する（提案の中身の良し悪しは採点しない＝ここは配線と写像だけ）。担保する点:
  1. 抽出        叙述文（プロース）だけを id/パス付きで集める（生活記録・仮名・タグ・日付は渡さない）
  2. 写像        AI が id で返した提案を entry の具体パスへ正しく写像する
  3. フィルタ     元と同一・空・対象外 id の提案は落とす（安全網）
"""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("google.adk", reason="google-adk 未インストール（uv sync 後に有効化）")

from typing import AsyncGenerator  # noqa: E402

from google.adk.models import BaseLlm, LlmResponse  # noqa: E402
from google.genai import types  # noqa: E402
from pydantic import PrivateAttr  # noqa: E402

from hoiku_agent.web import proofread  # noqa: E402


class FakeLlm(BaseLlm):
    """決定論E2E 用の LLM スタブ（テスト専用・creds 不要）。responses[i] を i 回目に返す。"""

    model: str = "fake-llm"
    responses: list[str]
    _calls: int = PrivateAttr(default=0)

    async def generate_content_async(
        self, llm_request, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        idx = min(self._calls, len(self.responses) - 1)
        self._calls += 1
        yield LlmResponse(
            content=types.Content(role="model", parts=[types.Part(text=self.responses[idx])])
        )


def _diary_entry() -> dict:
    """校正対象の叙述文を持つ手入力 diary（架空児のみ・§14）。id 順＝collect_items の順。"""
    return {
        "date": "2026-07-06",
        "age_band": "0-2",
        "weather": "晴れ",
        "daily_aim": "安心して好きな遊びに関わる",  # id 1
        "practice_record": "園庭で砂遊びを行った。",  # id 2
        "health_notes": None,  # 空＝対象外
        "parent_contact": None,  # 空＝対象外
        "individual_notes": [
            {
                "child_id": "架空児A",
                "observed_state": "砂の感触を確かめた",  # id 3
                "tags": ["身近なものと関わり感性が育つ"],
                "life_record": {"meal": "完食", "sleep": "午睡2時間"},  # 対象外（数量）
            }
        ],
        "evaluation": {"child_focus": "感触に集中", "self_review": "道具が適切"},  # id 4, 5
    }


def test_proofread_maps_suggestions_back_to_paths_and_filters():
    """AI が id で返した提案が entry のパスへ写像され、無効な提案は落ちる（②③）。"""
    # id 2（practice_record）→言い換え、id 3（observed_state）→言い換え、id 4→元と同一（落ちる）、
    # id 99→対象外 id（落ちる）、id 5→空提案（落ちる）。
    raw = (
        "校正の提案です。\n```json\n"
        '{"suggestions": ['
        '{"id": 2, "original": "園庭で砂遊びを行った。", "suggestion": "園庭で砂遊びを行いました。", "reason": "ですます", "kind": "phrasing"},'
        '{"id": 3, "suggestion": "砂の感触を確かめていました。", "reason": "様子が伝わる言い換え", "kind": "phrasing"},'
        '{"id": 4, "suggestion": "感触に集中", "reason": "同じ", "kind": "phrasing"},'
        '{"id": 5, "suggestion": "   ", "reason": "空", "kind": "phrasing"},'
        '{"id": 99, "suggestion": "対象外", "reason": "存在しない id", "kind": "phrasing"}'
        "]}\n```"
    )
    res = asyncio.run(
        proofread.proofread_entry("diary", _diary_entry(), model=FakeLlm(responses=[raw]))
    )

    by_path = {s["path"]: s for s in res["suggestions"]}
    # 有効な2件だけが残り、正しいパスへ写像される
    assert set(by_path) == {"practice_record", "individual_notes[0].observed_state"}
    assert by_path["practice_record"]["suggestion"] == "園庭で砂遊びを行いました。"
    assert (
        by_path["individual_notes[0].observed_state"]["suggestion"]
        == "砂の感触を確かめていました。"
    )
    # ラベルには子どもの呼び名が文脈として付く（個別記録）
    assert "架空児A" in by_path["individual_notes[0].observed_state"]["label"]
    # 対象文数は叙述文の数（生活記録・タグ・日付は含まない）
    assert res["checked"] == 5
    assert res["error"] is None


def test_proofread_no_suggestions_when_ai_returns_empty():
    """AI が改善なし（空配列）を返したら提案なし（無理に作らない）。"""
    raw = '気になる点はありませんでした。\n```json\n{"suggestions": []}\n```'
    res = asyncio.run(
        proofread.proofread_entry("diary", _diary_entry(), model=FakeLlm(responses=[raw]))
    )
    assert res["suggestions"] == [] and res["error"] is None


def test_proofread_empty_entry_skips_llm():
    """叙述文が空なら LLM を呼ばず（FakeLlm を渡さなくても）提案なしを返す＝非課金の早期リターン。"""
    entry = {
        "date": "2026-07-06",
        "age_band": "0-2",
        "attendance": [],
        "individual_notes": [],
        "evaluation": {},
    }
    res = asyncio.run(proofread.proofread_entry("diary", entry))
    assert res["suggestions"] == [] and res["checked"] == 0 and res["error"] is None
