"""個別月案パイプライン（L2 還流）の手動起動エントリ（設計コンテキスト §3/§4/§10）。

日誌は root_agent（doc_type 既定＝保育日誌）で `adk run`/`adk web` から回せるが、月案は前月日誌の
集積（L2 還流）を seed する必要があるため、専用スクリプトで起こす（root_agent には組み込み済みだが、
`adk web` は doc_type と前月日誌を seed しづらいので、デモ/検証はこの入口を使う）。

このスクリプトは:
1. 前月日誌（`--prev-entries-file` の JSON 配列。無ければ同梱の架空児サンプル）を読む。
2. session state に doc_type="月案" と prev_month_entries を seed して root_agent（DocTypeRouter）を回す。
3. MonthlyPrepAgent が child_id 別に集計（state["prev_month_digest"]）→ 月案 author が要約・ねらい化
   → reviewer → 月案 finalize（MonthlyPlan を検査・整形）。

使い方（要 LLM 資格情報＝Vertex/Gemini。`gcloud auth application-default login` 済み・.env 設定済み）:
    uv run python scripts/run_monthly.py --child-id 架空児A --month 2026-07
    uv run python scripts/run_monthly.py --prev-entries-file path/to/prev_diaries.json

前月日誌の JSON は DiaryEntry の配列（tests/test_e2e/test_monthly_e2e.py の _prev_entry と同型）。
実データは置かない＝架空児のみ（§14）。
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from google.genai import types

from hoiku_agent.agent import root_agent

_APP_NAME = "hoiku_monthly"
_USER_ID = "caregiver"


def _sample_prev_entries(child_id: str) -> list[dict]:
    """前月日誌の架空児サンプル（L2 還流のデモ入力）。実データは置かない（§14）。"""
    return [
        {
            "date": f"2026-06-{day:02d}",
            "age_band": "0-2",
            "weather": "晴れ",
            "attendance": [{"child_id": child_id, "present": True, "reason": None}],
            "practice_record": "園庭で感触遊びを行った。",
            "individual_notes": [
                {
                    "child_id": child_id,
                    "observed_state": f"6月{day}日：砂をすくって感触を確かめ、笑顔が見られた",
                    "tags": ["身近なものと関わり感性が育つ"],
                }
            ],
            "evaluation": {
                "child_focus": "感触に繰り返し関わっていた",
                "self_review": "素材を十分用意できた",
            },
        }
        for day in (24, 25, 26)
    ]


async def _run(month: str, child_id: str, prev_entries: list[dict]) -> None:
    from google.adk.runners import InMemoryRunner

    runner = InMemoryRunner(agent=root_agent, app_name=_APP_NAME)
    session = await runner.session_service.create_session(
        app_name=_APP_NAME,
        user_id=_USER_ID,
        state={"doc_type": "月案", "prev_month_entries": prev_entries},
    )
    message = types.Content(
        role="user",
        parts=[types.Part(text=f"{month} の {child_id} の個別月案を作成してください。")],
    )

    async for event in runner.run_async(
        user_id=_USER_ID, session_id=session.id, new_message=message
    ):
        if event.content and event.content.parts:
            for part in event.content.parts:
                if getattr(part, "text", None):
                    print(f"[{event.author}] {part.text}")
                if getattr(part, "function_call", None):
                    print(
                        f"[{event.author}] →tool {part.function_call.name}({part.function_call.args})"
                    )

    final = await runner.session_service.get_session(
        app_name=_APP_NAME, user_id=_USER_ID, session_id=session.id
    )
    print("\n--- 最終 state ---")
    print(
        "prev_month_digest:", json.dumps(final.state.get("prev_month_digest"), ensure_ascii=False)
    )
    print("validation:", final.state.get("validation"))
    print("final_document:\n", final.state.get("final_document"))


def main() -> None:
    parser = argparse.ArgumentParser(description="個別月案パイプライン（L2 還流）の手動起動")
    parser.add_argument("--month", default="2026-07", help="対象月（YYYY-MM）")
    parser.add_argument("--child-id", default="架空児A", help="対象児（架空児のみ＝§14）")
    parser.add_argument(
        "--prev-entries-file", help="前月日誌（DiaryEntry の JSON 配列）。無ければ同梱サンプル"
    )
    args = parser.parse_args()

    if args.prev_entries_file:
        prev_entries = json.loads(Path(args.prev_entries_file).read_text(encoding="utf-8"))
    else:
        prev_entries = _sample_prev_entries(args.child_id)

    asyncio.run(_run(args.month, args.child_id, prev_entries))


if __name__ == "__main__":
    main()
