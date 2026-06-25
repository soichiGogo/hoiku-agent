"""改善エージェント（二階）の手動起動エントリ（設計コンテキスト §8）。

一階の root_agent（document_pipeline）とは**別エントリ**で improver を手動起動するための専用スクリプト。
root_agent には組み込まない・自動起動しないという制約（improver/CLAUDE.md）を守りつつ、「閉じる1事例」
（保育士の修正差分 → 指針更新提案 →（競合なら保育士判断）→ ゲート → PR）を1周回すための入口。

使い方（要 LLM 資格情報＝Vertex/Gemini。`gcloud auth application-default login` 済み・.env 設定済み）:
    uv run python scripts/run_improver.py --diff "保育日誌の感触遊びは感触語と表情を併記したい" \
        --feedback "👍 ただし断定表現は避けたい"
    # または差分をファイルから:
    uv run python scripts/run_improver.py --diff-file path/to/diff.txt

improver は単一 LlmAgent で、propose_policy_change / run_eval / ask_caregiver / open_pr を必要に応じ呼ぶ。
ask_caregiver は LongRunningFunctionTool（HITL）なので、保育士への質問が出た場合はこの同期実行では
保留（pending）イベントが表示される（長期中断の本格対応は §6 未決）。open_pr は既定 dry_run。
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
    parts = [f"保育士の修正差分:\n{diff}"]
    if feedback:
        parts.append(f"\nフィードバック(👍👎):\n{feedback}")
    parts.append(
        "\n上記から育つ指針の更新を構造化編集で提案し、競合があれば二択を仰ぎ、run_eval の回帰チェックを経て"
        "open_pr（dry_run）で起票してください。"
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
