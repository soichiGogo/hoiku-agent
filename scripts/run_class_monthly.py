"""クラス月案パイプライン（園の実様式・L2 還流）の手動起動エントリ（設計コンテキスト §3/§10/§18）。

個別月案（run_monthly.py）と対称に、**園の実様式のクラス月案**（区分×領域グリッド＋0–2 の個人目標）を
前月日誌の集積（L2 還流）に乗せて回す専用スクリプト。個別月案が1児単位なのに対し、クラス月案は
クラス全体（＝年齢帯）単位で、前月の当該クラスの全登場児を集計して書く。

このスクリプトは:
1. 前月日誌を読む。優先順位＝ `--prev-entries-file`（JSON 配列）＞ 書類アーカイブ（`DATABASE_URL` 設定時・
   前月の当該年齢帯の日誌）＞ 同梱の仮名サンプル（複数児・降格）。
2. session state に doc_type="クラス月案" と prev_month_entries を seed して root_agent を回す。
3. DigestPrepAgent（class_month_prep）が child_id 別に集計（state["prev_month_digest"]）→ クラス月案 author が
   クラス全体のねらい・区分×領域グリッド・0–2 の個人目標を生成 → reviewer → finalize（検査・整形）。

使い方（要 LLM 資格情報＝Vertex/Gemini。`gcloud auth application-default login` 済み・.env 設定済み）:
    uv run python scripts/run_class_monthly.py --age-band 0-2 --month 2026-07
    uv run python scripts/run_class_monthly.py --prev-entries-file path/to/prev_diaries.json

前月日誌の JSON は DiaryEntry の配列（tests/test_e2e/test_class_monthly_e2e.py の _prev_entry と同型）。
実データは置かない＝実在しない仮名のみ（§14）。
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from google.genai import types

from hoiku_agent.agent import root_agent

_APP_NAME = "hoiku_class_monthly"
_USER_ID = "caregiver"

_AGE_LABEL = {"0-2": "0〜2歳児クラス", "3-5": "3歳以上児クラス"}


def _sample_prev_entries(age_band: str) -> list[dict]:
    """前月のクラスの日誌サンプル（L2 還流のデモ入力）。実データは置かない＝実在しない仮名のみ（§14）。

    クラス全体なので**複数の仮名児**を登場させる（digest がクラス全登場児ぶんになり、0–2 は個人目標が
    児ごとに生成される）。年齢帯で内容を切替（0–2＝3視点・生活記録あり／3–5＝5領域・生活記録なし）。
    """
    if age_band == "3-5":
        roster = [
            (
                "さくらちゃん",
                "4歳2か月",
                "鬼ごっこでルールを友だちに説明していた",
                ["人間関係"],
                None,
            ),
            (
                "れんくん",
                "4歳5か月",
                "積み木で友だちと街を作り役割を分担した",
                ["言葉", "人間関係"],
                None,
            ),
            ("みおちゃん", "4歳0か月", "散歩で見つけた葉の色や形の違いに気づいた", ["環境"], None),
        ]
    else:
        roster = [
            (
                "はるとくん",
                "1歳3か月",
                "歩行が安定し玩具を自分で選んで手渡した",
                ["健やかに伸び伸びと育つ"],
                {
                    "meal": "完了期を全量摂取",
                    "sleep": "12:15〜14:10 午睡",
                    "toilet": "排尿4回・排便1回",
                    "mood_health": "体温36.5℃・機嫌よし",
                },
            ),
            (
                "ゆいちゃん",
                "1歳1か月",
                "砂場でスコップに砂をすくっては空けて見つめた",
                ["身近なものと関わり感性が育つ"],
                {
                    "meal": "後期食を8割",
                    "sleep": "12:20〜14:20 午睡",
                    "toilet": "排尿5回・排便1回",
                    "mood_health": "体温36.6℃・変化なし",
                },
            ),
            (
                "そうたくん",
                "0歳11か月",
                "絵本の動物を指さして声を出し保育者に見せようとした",
                ["身近な人と気持ちが通じ合う"],
                {
                    "meal": "後期食を9割",
                    "sleep": "12:10〜14:00 午睡",
                    "toilet": "排尿4回・排便1回",
                    "mood_health": "体温36.5℃・機嫌よし",
                },
            ),
        ]
    entries: list[dict] = []
    for day in ("2026-06-12", "2026-06-26"):
        for child, months, state, tags, life in roster:
            entries.append(
                {
                    "date": day,
                    "age_band": age_band,
                    "weather": "晴れ",
                    "attendance": [{"child_id": child, "present": True, "reason": None}],
                    "practice_record": "クラスの子どもの興味に応じた遊びを用意した。",
                    "individual_notes": [
                        {
                            "child_id": child,
                            "age_months": months,
                            "observed_state": state,
                            "tags": tags,
                            "life_record": life or {},
                        }
                    ],
                    "evaluation": {
                        "child_focus": "興味の対象に自分から関わっていた",
                        "self_review": "発達に合わせた環境を用意できた",
                    },
                }
            )
    return entries


def _archive_prev_entries(month: str, age_band: str) -> list[dict]:
    """書類アーカイブから前月の当該年齢帯の日誌を引く（L2 seed の本命経路・Phase 1）。

    DATABASE_URL 未設定・月の解釈不能・該当なしは []＝呼び出し側がサンプルへ降格する。
    年齢帯フィルタはクラス月案がクラス（＝年齢帯）単位のため（他クラスの姿を混ぜない）。
    """
    from hoiku_agent.harness import record_store

    try:
        date_from, date_to = record_store.month_date_range(record_store.prev_month_of(month))
    except ValueError:
        return []
    entries = record_store.list_diary_entries(date_from, date_to)
    return [e for e in entries if (e.get("age_band") or "0-2") == age_band]


async def _run(month: str, age_band: str, prev_entries: list[dict]) -> None:
    from google.adk.runners import InMemoryRunner

    runner = InMemoryRunner(agent=root_agent, app_name=_APP_NAME)
    session = await runner.session_service.create_session(
        app_name=_APP_NAME,
        user_id=_USER_ID,
        state={"doc_type": "クラス月案", "prev_month_entries": prev_entries},
    )
    label = _AGE_LABEL.get(age_band, age_band)
    message = types.Content(
        role="user",
        parts=[
            types.Part(
                text=f"{month} の {label} のクラス月案を作成してください。"
                f"month には「{month}」、age_band には「{age_band}」をそのまま書いてください。"
            )
        ],
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
    parser = argparse.ArgumentParser(
        description="クラス月案パイプライン（園の実様式・L2 還流）の手動起動"
    )
    parser.add_argument("--month", default="2026-07", help="対象月（YYYY-MM）")
    parser.add_argument(
        "--age-band", default="0-2", choices=["0-2", "3-5"], help="クラス（年齢帯）"
    )
    parser.add_argument(
        "--prev-entries-file", help="前月日誌（DiaryEntry の JSON 配列）。無ければ同梱サンプル"
    )
    args = parser.parse_args()

    if args.prev_entries_file:
        prev_entries = json.loads(Path(args.prev_entries_file).read_text(encoding="utf-8"))
        seed_src = f"ファイル {args.prev_entries_file}"
    else:
        prev_entries = _archive_prev_entries(args.month, args.age_band)
        seed_src = "書類アーカイブ（DATABASE_URL）"
        if not prev_entries:
            prev_entries = _sample_prev_entries(args.age_band)
            seed_src = "同梱サンプル（アーカイブ未設定/該当なし＝降格）"
    print(f"[seed] 前月日誌 {len(prev_entries)} 件（{seed_src}・クラス={args.age_band}）")

    asyncio.run(_run(args.month, args.age_band, prev_entries))


if __name__ == "__main__":
    main()
