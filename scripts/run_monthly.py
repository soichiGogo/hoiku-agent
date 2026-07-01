"""個別月案パイプライン（L2 還流）の手動起動エントリ（設計コンテキスト §3/§4/§10）。

日誌は root_agent（doc_type 既定＝保育日誌）で `adk run`/`adk web` から回せるが、月案は前月日誌の
集積（L2 還流）を seed する必要があるため、専用スクリプトで起こす（root_agent には組み込み済みだが、
`adk web` は doc_type と前月日誌を seed しづらいので、デモ/検証はこの入口を使う）。

このスクリプトは:
1. 前月日誌（`--prev-entries-file` の JSON 配列。無ければ同梱の仮名サンプル）を読む。
2. session state に doc_type="月案" と prev_month_entries を seed して root_agent（DocTypeRouter）を回す。
3. MonthlyPrepAgent が child_id 別に集計（state["prev_month_digest"]）→ 月案 author が要約・ねらい化
   → reviewer → 月案 finalize（MonthlyPlan を検査・整形）。

使い方（要 LLM 資格情報＝Vertex/Gemini。`gcloud auth application-default login` 済み・.env 設定済み）:
    uv run python scripts/run_monthly.py --child-id はるとくん --month 2026-07
    uv run python scripts/run_monthly.py --prev-entries-file path/to/prev_diaries.json

前月日誌の JSON は DiaryEntry の配列（tests/test_e2e/test_monthly_e2e.py の _prev_entry と同型）。
実データは置かない＝実在しない仮名のみ（§14。既定サンプルの子は eval の仮名ロスターと同じ）。
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
    """前月日誌のサンプル（L2 還流のデモ入力）。実データは置かない＝実在しない仮名のみ（§14）。

    現場に即した 0–2 個別記録（月齢・数量化した生活記録・具体的な姿）で、前月の複数日を
    child_id 別に集積 → 月案の「前月の子どもの姿／評価・反省」へ流れる素材にする。
    各要素は DiaryEntry として妥当（_parse_prev_entries が model_validate で復元する）。
    """
    days = [
        {
            "date": "2026-06-24",
            "weather": "晴れ",
            "practice_record": "園庭の砂場で感触遊びを行った。",
            "observed_state": "砂場でスコップに砂をすくっては空ける動作を繰り返し、こぼれる様子をじっと見つめた",
            "tags": ["身近なものと関わり感性が育つ"],
            "meal": "完了期の給食を8割摂取、麦茶80ml",
            "sleep": "12:15〜14:20 午睡",
            "toilet": "排尿4回・排便1回",
            "mood_health": "視診で体温36.5℃、機嫌よく変化なし",
            "child_focus": "素材の感触に繰り返し関わっていた",
            "self_review": "スコップやカップを人数分用意できた",
        },
        {
            "date": "2026-06-26",
            "weather": "くもり",
            "practice_record": "室内で歩行や移動を促す環境を整えた。",
            "observed_state": "両手を広げてバランスを取りながら数歩歩き、保育者のもとへ進もうとした",
            "tags": ["健やかに伸び伸びと育つ"],
            "meal": "完了期の給食を9割摂取",
            "sleep": "12:20〜14:30 ぐっすり午睡",
            "toilet": "排尿5回・排便1回",
            "mood_health": "視診で体温36.6℃、活発で気になる点なし",
            "child_focus": "自分から体を動かそうとする意欲が高まっていた",
            "self_review": "転倒に備えマットと広い動線を用意できた",
        },
        {
            "date": "2026-06-30",
            "weather": "晴れ",
            "practice_record": "少人数で絵本を読み、指さしや発声に応じた。",
            "observed_state": "絵本の動物を指さして声を出し、保育者に見せようとした",
            "tags": ["身近な人と気持ちが通じ合う"],
            "meal": "完了期の給食を全量摂取、麦茶90ml",
            "sleep": "12:15〜14:10 午睡",
            "toilet": "排尿4回・排便1回",
            "mood_health": "視診で体温36.6℃、機嫌よく変化なし",
            "child_focus": "好きなものを見つけ、伝えたい気持ちが育っていた",
            "self_review": "発見に共感的に応答し、繰り返しを楽しめるようにした",
        },
    ]
    return [
        {
            "date": d["date"],
            "age_band": "0-2",
            "weather": d["weather"],
            "attendance": [{"child_id": child_id, "present": True, "reason": None}],
            "practice_record": d["practice_record"],
            "individual_notes": [
                {
                    "child_id": child_id,
                    "age_months": "1歳3か月",
                    "observed_state": d["observed_state"],
                    "tags": d["tags"],
                    "life_record": {
                        "meal": d["meal"],
                        "sleep": d["sleep"],
                        "toilet": d["toilet"],
                        "mood_health": d["mood_health"],
                    },
                }
            ],
            "evaluation": {
                "child_focus": d["child_focus"],
                "self_review": d["self_review"],
            },
        }
        for d in days
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
    parser.add_argument(
        "--child-id", default="はるとくん", help="対象児（実在しない仮名のみ＝§14）"
    )
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
