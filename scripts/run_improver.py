"""改善エージェント（二階）の手動起動エントリ（設計コンテキスト §8）。

一階の root_agent（document_pipeline）とは**別エントリ**で improver を手動起動するための専用スクリプト。
root_agent には組み込まない・自動起動しないという制約（improver/CLAUDE.md）を守りつつ、「閉じる1事例」
（保育士の修正メモ → カード案＋意味的競合精査 →（競合なら比較相談）→ 保育士決定 → 即反映）を1周回す入口。

使い方（要 LLM 資格情報＝Vertex/Gemini。`gcloud auth application-default login` 済み・.env 設定済み）:
    uv run python scripts/run_improver.py --diff "保育日誌の感触遊びは感触語と表情を併記したい" \
        --feedback "👍 ただし断定表現は避けたい"
    # または差分をファイルから:
    uv run python scripts/run_improver.py --diff-file path/to/diff.txt

improver は単一 LlmAgent で、read_policy_cards / propose_policy_card / ask_caregiver / commit_policy_card
を必要に応じ呼ぶ。ask_caregiver は LongRunningFunctionTool（HITL）なので、保育士への相談が出た場合は
この同期実行では保留（pending）イベントが表示される（再開は Web の /api/improve/resume）。指針への反映は
保育士の決定で即時（commit_policy_card）＝評価ゲートは通さない。
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from google.genai import types

from hoiku_agent.improver import build_improver_agent

_APP_NAME = "hoiku_improver"
_USER_ID = "caregiver"


def _build_input(diff: str, feedback: str | None) -> str:
    parts = [f"保育士の修正メモ:\n{diff}"]
    if feedback:
        parts.append(f"\nフィードバック(👍👎):\n{feedback}")
    parts.append(
        "\n上記がほかの書類・子にも当てはまる**一般化できる勘所**なら、育つ指針カードの追加/改訂案を作り、"
        "既存カードと意味的に競合しないか精査してください。競合があれば該当カードと比較相談し、保育士の決定で"
        "即反映（commit_policy_card）してください。特定の書類・場面に固有で一般化できない気づきなら、"
        "その旨を一言述べて指針は変更しないでください（フィードバックは既に保存済みです）。"
    )
    return "\n".join(parts)


async def _run(diff: str, feedback: str | None) -> None:
    from google.adk.runners import InMemoryRunner

    runner = InMemoryRunner(agent=build_improver_agent(), app_name=_APP_NAME)
    session = await runner.session_service.create_session(app_name=_APP_NAME, user_id=_USER_ID)
    message = types.Content(role="user", parts=[types.Part(text=_build_input(diff, feedback))])

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
    print("policy_change:", final.state.get("policy_change"))


def main() -> None:
    parser = argparse.ArgumentParser(description="改善エージェント（二階）の手動起動")
    parser.add_argument("--diff", help="保育士の修正差分（テキスト）")
    parser.add_argument("--diff-file", help="修正差分を読むファイルパス")
    parser.add_argument("--feedback", help="👍👎・補足フィードバック（任意）")
    args = parser.parse_args()

    if args.diff_file:
        diff = Path(args.diff_file).read_text(encoding="utf-8")
    elif args.diff:
        diff = args.diff
    else:
        parser.error("--diff か --diff-file のいずれかを指定してください")

    asyncio.run(_run(diff, args.feedback))


if __name__ == "__main__":
    main()
