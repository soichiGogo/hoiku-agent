"""保育経過記録パイプライン（L3 還流）の手動起動エントリ（設計コンテキスト §19）。

月案（run_monthly.py）と対称。保育経過記録は期間中の日誌の集積（L3 還流）を seed する必要があるため、
専用スクリプトで起こす（root_agent には組み込み済みだが、`adk web` は doc_type と期間日誌を
seed しづらいので、デモ/検証はこの入口を使う）。

このスクリプトは:
1. 期間中の日誌を読む。優先順位＝ `--entries-file`（JSON 配列）＞ 書類アーカイブ
   （`DATABASE_URL` 設定時・record_store から期間分を取得＝Phase 1）＞ 同梱の仮名サンプル（降格）。
   併せて**前回までの保育経過記録**（その児の作成済み過去の記録すべて・作成対象の期は除外＝依存モデル
   2026-07）をアーカイブから引く（未接続/初回は 0 件＝降格）。
2. session state に doc_type="保育経過記録" と period_entries・prev_record_entries を seed して
   root_agent（DocTypeRouter）を回す。
3. 保育経過記録 author が参照方針カードに従い fetch_reference で期間日誌と前回までの記録を選択取得し、
   前期からの連続性を踏まえ領域別の叙述・総合所見へ再構成（開示前提の表現）→ reviewer →
   保育経過記録 finalize（ChildRecord を検査・整形）。

使い方（要 LLM 資格情報＝Vertex/Gemini。`gcloud auth application-default login` 済み・.env 設定済み）:
    uv run python scripts/run_child_record.py --child-id はるとくん --period 2026-04〜2026-06
    uv run python scripts/run_child_record.py --entries-file path/to/period_diaries.json

期間日誌の JSON は DiaryEntry の配列（run_monthly.py の前月日誌と同型）。
実データは置かない＝実在しない仮名のみ（§14。既定サンプルの子は eval の仮名ロスターと同じ）。
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from google.genai import types

from hoiku_agent.agent import root_agent

_APP_NAME = "hoiku_child_record"
_USER_ID = "caregiver"


def _sample_period_entries(child_id: str) -> list[dict]:
    """期間中の日誌サンプル（L3 還流のデモ入力）。実データは置かない＝実在しない仮名のみ（§14）。

    3ヶ月にわたる発達の推移（つかまり立ち→歩行→指さし・発語）を含め、保育経過記録の
    「点の記録 → 期の育ちの線」への再構成が見える素材にする（§19）。
    各要素は DiaryEntry として妥当（_parse_prev_entries が model_validate で復元する）。
    """
    days = [
        {
            "date": "2026-04-10",
            "age_months": "1歳1か月",
            "observed_state": "つかまり立ちから伝い歩きで棚に沿って移動し、玩具に手を伸ばした",
            "tags": ["健やかに伸び伸びと育つ"],
            "practice_record": "つかまり立ちを促す安全な環境を整えた。",
            "meal": "離乳食後期を7割",
            "sleep": "12:00〜14:00 午睡",
            "toilet": "排尿4回・排便1回",
            "mood_health": "視診で体温36.5℃、機嫌よし",
        },
        {
            "date": "2026-04-24",
            "age_months": "1歳1か月",
            "observed_state": "保育者の歌に合わせて体を揺らし、目が合うと声を出して笑った",
            "tags": ["身近な人と気持ちが通じ合う"],
            "practice_record": "ふれあい遊びで応答的に関わった。",
            "meal": "離乳食後期を8割",
            "sleep": "12:10〜14:05 午睡",
            "toilet": "排尿4回・排便1回",
            "mood_health": "視診で体温36.6℃、変化なし",
        },
        {
            "date": "2026-05-15",
            "age_months": "1歳2か月",
            "observed_state": "両手を離して2〜3歩歩き、保育者のもとへ進もうとした",
            "tags": ["健やかに伸び伸びと育つ"],
            "practice_record": "広い動線とマットで歩行を支えた。",
            "meal": "完了期へ移行し8割",
            "sleep": "12:15〜14:20 午睡",
            "toilet": "排尿5回・排便1回",
            "mood_health": "視診で体温36.5℃、機嫌よし",
        },
        {
            "date": "2026-05-29",
            "age_months": "1歳2か月",
            "observed_state": "砂場でスコップに砂をすくっては空け、こぼれる様子をじっと見つめた",
            "tags": ["身近なものと関わり感性が育つ"],
            "practice_record": "砂・水の感触遊びを用意した。",
            "meal": "完了期を8割・麦茶80ml",
            "sleep": "12:15〜14:15 午睡",
            "toilet": "排尿4回・排便1回",
            "mood_health": "視診で体温36.6℃、変化なし",
        },
        {
            "date": "2026-06-12",
            "age_months": "1歳3か月",
            "observed_state": "絵本の動物を指さして「わんわん」と声を出し、保育者に見せようとした",
            "tags": ["身近な人と気持ちが通じ合う", "身近なものと関わり感性が育つ"],
            "practice_record": "少人数で絵本を読み指さしに応じた。",
            "meal": "完了期を9割",
            "sleep": "12:20〜14:30 午睡",
            "toilet": "排尿5回・排便1回",
            "mood_health": "視診で体温36.6℃、機嫌よし",
        },
        {
            "date": "2026-06-26",
            "age_months": "1歳3か月",
            "observed_state": "安定して歩き、好きな玩具を自分で選んで保育者に手渡した",
            "tags": ["健やかに伸び伸びと育つ"],
            "practice_record": "自分で選べる玩具棚の配置にした。",
            "meal": "完了期を全量摂取",
            "sleep": "12:15〜14:10 午睡",
            "toilet": "排尿4回・排便1回",
            "mood_health": "視診で体温36.5℃、機嫌よし",
        },
    ]
    return [
        {
            "date": d["date"],
            "age_band": "0-2",
            "weather": "晴れ",
            "attendance": [{"child_id": child_id, "present": True, "reason": None}],
            "practice_record": d["practice_record"],
            "individual_notes": [
                {
                    "child_id": child_id,
                    "age_months": d["age_months"],
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
                "child_focus": "興味の対象に自分から関わっていた",
                "self_review": "発達に合わせた環境を用意できた",
            },
        }
        for d in days
    ]


def _archive_period_entries(period: str) -> list[dict]:
    """書類アーカイブから期間中の日誌を引く（L3 seed の本命経路・Phase 1）。

    DATABASE_URL 未設定・期間の解釈不能（期制は園差＝自由記述）・該当なしは []＝
    呼び出し側がサンプルへ降格する（黙って誤解釈しない）。
    """
    from hoiku_agent.harness import record_store

    span = record_store.period_date_range(period)
    if span is None:
        return []
    return record_store.list_diary_entries(*span)


def _archive_prev_records(child_id: str, period: str) -> list[dict]:
    """書類アーカイブから前回までの保育経過記録を引く（自己履歴 seed・依存モデル 2026-07）。

    その児の作成済み記録すべて（全期・年度跨ぎ含む）から、作成対象の期そのものを除いて返す。
    未接続・該当なし（初回）は []＝prev_records_digest が空で降格（作成は止めない）。
    """
    from hoiku_agent.harness import record_store

    return record_store.list_child_record_entries(child_id, exclude_period=period)


async def _run(
    period: str, child_id: str, period_entries: list[dict], prev_records: list[dict]
) -> None:
    from google.adk.runners import InMemoryRunner

    runner = InMemoryRunner(agent=root_agent, app_name=_APP_NAME)
    session = await runner.session_service.create_session(
        app_name=_APP_NAME,
        user_id=_USER_ID,
        state={
            "doc_type": "保育経過記録",
            "period_entries": period_entries,
            "prev_record_entries": prev_records,
        },
    )
    message = types.Content(
        role="user",
        parts=[
            types.Part(
                text=(
                    f"対象期間 {period} の {child_id} の保育経過記録を作成してください。"
                    f"period には「{period}」をそのまま書いてください。"
                )
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
    parser = argparse.ArgumentParser(description="保育経過記録パイプライン（L3 還流）の手動起動")
    parser.add_argument("--period", default="2026-04〜2026-06", help="対象期間（自由記述）")
    parser.add_argument(
        "--child-id", default="はるとくん", help="対象児（実在しない仮名のみ＝§14）"
    )
    parser.add_argument(
        "--entries-file", help="期間中の日誌（DiaryEntry の JSON 配列）。無ければ同梱サンプル"
    )
    args = parser.parse_args()

    if args.entries_file:
        period_entries = json.loads(Path(args.entries_file).read_text(encoding="utf-8"))
        seed_src = f"ファイル {args.entries_file}"
    else:
        period_entries = _archive_period_entries(args.period)
        seed_src = "書類アーカイブ（DATABASE_URL）"
        if not period_entries:
            period_entries = _sample_period_entries(args.child_id)
            seed_src = "同梱サンプル（アーカイブ未設定/該当なし＝降格）"
    print(f"[seed] 期間日誌 {len(period_entries)} 件（{seed_src}）")

    # 前回までの保育経過記録（自己履歴）＝アーカイブから全期を引く（初回/未接続は 0 件＝降格）。
    prev_records = _archive_prev_records(args.child_id, args.period)
    print(
        f"[seed] 前回までの保育経過記録 {len(prev_records)} 件（書類アーカイブ・作成対象の期は除外）"
    )

    asyncio.run(_run(args.period, args.child_id, period_entries, prev_records))


if __name__ == "__main__":
    main()
