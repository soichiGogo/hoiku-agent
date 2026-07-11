"""クラス月案パイプライン（園の実様式）の手動起動エントリ（設計コンテキスト §3/§10/§18・依存モデル 2026-07）。

個別月案（run_monthly.py）と対称に、**園の実様式のクラス月案**（区分×領域グリッド＋0–2 の個人目標）を
3系統の蓄積に乗せて回す専用スクリプト。個別月案が1児単位なのに対し、クラス月案はクラス全体
（＝年齢帯）単位で書く。

このスクリプトは:
1. seed（3系統＋在籍児名簿）を読む（依存モデル 2026-07）＝ `record_store.class_monthly_seed_inputs` の合成:
   ① クラス児童の作成済み保育経過記録すべて（全期・名簿優先） ② それまでのクラス月案すべて
   ③ 保育経過記録に未反映の期間の当該クラスの日誌（境界＝①の期間末）
   ④ クラスの在籍児名簿（クラス・園児マスタ＝0–2 個人目標の対象の与件・名簿未整備は空）。
   `--prev-entries-file`（JSON 配列）は③を手渡しで差し替える。未接続/該当なしは
   同梱の仮名サンプル（③のみ・複数児）へ降格。
2. session state に doc_type="クラス月案" と class_record_entries・past_class_plans・
   class_diary_entries・class_roster を seed して root_agent を回す。
3. author が reference_policy に従い3系統を fetch_reference で選択取得し、
   クラス全体のねらい・区分×領域グリッド・0–2 の個人目標を生成（計画の連続性・
   PDCA）→ reviewer → finalize（検査・整形）。

使い方（要 LLM 資格情報＝Vertex/Gemini。`gcloud auth application-default login` 済み・.env 設定済み）:
    uv run python scripts/run_class_monthly.py --age-band 0-2 --month 2026-07
    uv run python scripts/run_class_monthly.py --prev-entries-file path/to/diaries.json

日誌の JSON は DiaryEntry の配列（tests/test_e2e/test_class_monthly_e2e.py の _prev_entry と同型）。
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
    """クラスの日誌サンプル（未反映期間の想定・デモ入力）。実データは置かない＝実在しない仮名のみ（§14）。

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


def _archive_seed_inputs(month: str, age_band: str) -> dict:
    """書類アーカイブから seed 3系統を合成して引く（本命経路・依存モデル 2026-07）。

    合成の実体は `record_store.class_monthly_seed_inputs`（境界計算＝covered_until に1つ）。
    DATABASE_URL 未設定・該当なしは全部空＝呼び出し側が日誌サンプルへ降格する。
    月の解釈不能は ValueError を空へ降格（黙って誤解釈しない・サンプルで回る）。
    """
    from hoiku_agent.harness import record_store

    try:
        return record_store.class_monthly_seed_inputs(age_band, month)
    except ValueError:
        return {
            "class_diary_entries": [],
            "class_record_entries": [],
            "past_class_plans": [],
            "class_roster": [],
        }


async def _run(month: str, age_band: str, seed: dict) -> None:
    from google.adk.runners import InMemoryRunner

    runner = InMemoryRunner(agent=root_agent, app_name=_APP_NAME)
    session = await runner.session_service.create_session(
        app_name=_APP_NAME,
        user_id=_USER_ID,
        state={"doc_type": "クラス月案", **seed},
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
    print("reference_manifest:", final.state.get("reference_manifest"))
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
        "--prev-entries-file",
        help="日誌（DiaryEntry の JSON 配列）＝③未反映期間ぶんの手渡し。無ければアーカイブ→サンプル",
    )
    args = parser.parse_args()

    seed = _archive_seed_inputs(args.month, args.age_band)
    diary_src = "書類アーカイブ（DATABASE_URL）"
    if args.prev_entries_file:
        seed["class_diary_entries"] = json.loads(
            Path(args.prev_entries_file).read_text(encoding="utf-8")
        )
        diary_src = f"ファイル {args.prev_entries_file}"
    elif not seed["class_diary_entries"]:
        seed["class_diary_entries"] = _sample_prev_entries(args.age_band)
        diary_src = "同梱サンプル（アーカイブ未設定/該当なし＝降格）"
    print(
        f"[seed] クラス児童の保育経過記録 {len(seed['class_record_entries'])} 件 / "
        f"それまでのクラス月案 {len(seed['past_class_plans'])} 件（いずれも書類アーカイブ・"
        f"未接続は 0 件降格）"
    )
    roster = seed.get("class_roster") or []
    print(
        f"[seed] 在籍児名簿 {len(roster)} 名"
        + ("（名簿未整備/未接続＝記録の登場児で作成）" if not roster else "（クラス・園児マスタ）")
    )
    print(
        f"[seed] 未反映期間の日誌 {len(seed['class_diary_entries'])} 件"
        f"（{diary_src}・クラス={args.age_band}）"
    )

    asyncio.run(_run(args.month, args.age_band, seed))


if __name__ == "__main__":
    main()
