"""保育要録パイプライン（L4 還流）の手動起動エントリ（設計コンテキスト §19・集積階層の最終段）。

保育経過記録（run_child_record.py）と対称。保育要録は**最終年度（年長）の保育経過記録の集積（L4 還流）**を
seed する必要があるため、専用スクリプトで起こす（root_agent には組み込み済みだが、`adk web` は
doc_type と最終年度の保育経過記録を seed しづらいので、デモ/検証はこの入口を使う）。

このスクリプトは:
1. 最終年度の保育経過記録を読む。優先順位＝ `--entries-file`（JSON 配列）＞ 書類アーカイブ
   （`DATABASE_URL` 設定時・record_store から指定児の保育経過記録を取得＝Phase 1）＞ 同梱の仮名サンプル（降格）。
2. session state に doc_type="保育要録" と record_entries を seed して root_agent（DocTypeRouter）を回す。
3. RecordDigestPrepAgent（record_prep）が child_id 別に集計（state["record_digest"]）→ 要録 author が
   保育の展開・個人の重点・最終年度に至るまでの育ちへ再構成（開示前提＝小学校引継ぎ）→ reviewer →
   要録 finalize（NurseryRecord を検査・整形）。

使い方（要 LLM 資格情報＝Vertex/Gemini。`gcloud auth application-default login` 済み・.env 設定済み）:
    uv run python scripts/run_youroku.py --child-id はるとくん --fiscal-year 2026
    uv run python scripts/run_youroku.py --entries-file path/to/final_year_child_records.json

最終年度の保育経過記録の JSON は ChildRecord の配列（run_child_record.py の出力と同型）。
実データは置かない＝実在しない仮名のみ（§14。既定サンプルの子は eval の仮名ロスターと同じ）。
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from google.genai import types

from hoiku_agent.agent import root_agent

_APP_NAME = "hoiku_nursery_record"
_USER_ID = "caregiver"


def _sample_record_entries(child_id: str) -> list[dict]:
    """最終年度（年長=3–5）の保育経過記録サンプル（L4 還流のデモ入力）。実データは置かない＝仮名のみ（§14）。

    3期にわたる年長1年間の育ちの推移（自己発揮→協同→就学期待）を含め、要録の
    「期の記録 → 1年の育ちの線」への再構成が見える素材にする（§19）。
    各要素は ChildRecord として妥当（_parse_record_entries が model_validate で復元する）。
    """
    periods = [
        {
            "period": "2026-04〜2026-07",
            "age_months": "5歳4か月",
            "development": [
                (
                    "進級当初は新しい環境に戸惑いも見られたが、生活の流れが分かると安心して過ごした",
                    "健康",
                ),
                ("鬼ごっこなど走る遊びを好み、気の合う友だちと関わって遊んだ", "人間関係"),
            ],
            "overall": "新しい環境に慣れ、好きな遊びを見つけて自分を発揮し始めた",
            "next": "友だちとの関わりをさらに広げていく",
        },
        {
            "period": "2026-08〜2026-11",
            "age_months": "5歳8か月",
            "development": [
                ("製作活動で自分なりの思いを描き加えながら満足感を味わった", "表現"),
                ("散歩で摘んできた草花に興味をもち、図鑑で名前や色を調べようとした", "環境"),
            ],
            "overall": "自分の思いを表現しようとする姿が増え、探究する意欲が育った",
            "next": "言葉で伝え合う楽しさを広げていく",
        },
        {
            "period": "2026-12〜2027-03",
            "age_months": "6歳0か月",
            "development": [
                ("メッセージボード作りが友だちに広がり、伝え合う喜びを味わった", "言葉"),
                ("就学への期待をもち、当番活動に責任をもって取り組んだ", "人間関係"),
            ],
            "overall": "自信をもって表現し、就学に向けて意欲的に生活する姿が育った",
            "next": "小学校生活への期待をもって過ごす",
        },
    ]
    return [
        {
            "period": p["period"],
            "age_band": "3-5",
            "child_id": child_id,
            "age_months": p["age_months"],
            "development_notes": [
                {"description": desc, "tags": [tag]} for desc, tag in p["development"]
            ],
            "care_notes": "",
            "family_liaison": "",
            "overall_note": p["overall"],
            "next_aims": p["next"],
        }
        for p in periods
    ]


def _archive_record_entries(child_id: str) -> list[dict]:
    """書類アーカイブから指定児の保育経過記録を引く（L4 seed の本命経路・Phase 1）。

    最終年度分の保育経過記録を集積の素にする。DATABASE_URL 未設定・該当なしは []＝呼び出し側がサンプルへ
    降格する。年度での絞り込みは v0 では行わず全期を渡す（digest は渡された分を集計・§19 の残課題）。
    """
    from hoiku_agent.harness import record_store

    return record_store.list_child_record_entries(child_id)


async def _run(fiscal_year: str, child_id: str, record_entries: list[dict]) -> None:
    from google.adk.runners import InMemoryRunner

    runner = InMemoryRunner(agent=root_agent, app_name=_APP_NAME)
    session = await runner.session_service.create_session(
        app_name=_APP_NAME,
        user_id=_USER_ID,
        state={"doc_type": "保育要録", "record_entries": record_entries},
    )
    message = types.Content(
        role="user",
        parts=[
            types.Part(
                text=(
                    f"{fiscal_year}年度の {child_id} の保育要録（保育所児童保育要録）を作成してください。"
                    f"fiscal_year には「{fiscal_year}」をそのまま書いてください。"
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
    print("record_digest:", json.dumps(final.state.get("record_digest"), ensure_ascii=False))
    print("validation:", final.state.get("validation"))
    print("final_document:\n", final.state.get("final_document"))


def main() -> None:
    parser = argparse.ArgumentParser(description="保育要録パイプライン（L4 還流）の手動起動")
    parser.add_argument("--fiscal-year", default="2026", help="対象年度（自由記述）")
    parser.add_argument(
        "--child-id", default="はるとくん", help="対象児（実在しない仮名のみ＝§14）"
    )
    parser.add_argument(
        "--entries-file",
        help="最終年度の保育経過記録（ChildRecord の JSON 配列）。無ければ同梱サンプル",
    )
    args = parser.parse_args()

    if args.entries_file:
        record_entries = json.loads(Path(args.entries_file).read_text(encoding="utf-8"))
        seed_src = f"ファイル {args.entries_file}"
    else:
        record_entries = _archive_record_entries(args.child_id)
        seed_src = "書類アーカイブ（DATABASE_URL）"
        if not record_entries:
            record_entries = _sample_record_entries(args.child_id)
            seed_src = "同梱サンプル（アーカイブ未設定/該当なし＝降格）"
    print(f"[seed] 最終年度の保育経過記録 {len(record_entries)} 件（{seed_src}）")

    asyncio.run(_run(args.fiscal_year, args.child_id, record_entries))


if __name__ == "__main__":
    main()
