"""improver（二階「回す」）を Web から SSE 駆動する口（設計コンテキスト §8）。

一階の document_pipeline とは**別エントリ**で improver を起こす原則（improver/CLAUDE.md）を守るため、
ADK の app（root_agent）には載せず、ここで `build_improver_agent` を InMemoryRunner で回す
（scripts/run_improver.py と同型）。回す全体（提案→競合二択→評価ゲート→PR）の中間生成物を
そのままフロントのパネルに流すのが目的＝審査点②の可視化。

セッション保持（resume 用）はプロセス内 dict。配布デモ（Cloud Run・単一インスタンス想定）では十分で、
スケールアウト時は共有ストアが要る（v0 の既知の制限）。決定的ロジック・採点は持たない（eval が唯一実装）。
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from google.genai import types
from pydantic import BaseModel

from ..improver import build_improver_agent

_APP_NAME = "hoiku_improver"
_USER_ID = "caregiver"

# improve_session_id -> (runner, adk_session_id)。resume（競合二択の回答）で同一 invocation を継ぐ。
_SESSIONS: dict[str, tuple[Any, str]] = {}


class ImproveRequest(BaseModel):
    diff: str
    feedback: str | None = None
    # 保育士が選んだ対象書類（PolicyScope 値・None＝すべて＝AI 判断）。
    target_scope: str | None = None
    session_id: str | None = None  # フロントが採番（resume と対応づけ）


class ImproveResumeRequest(BaseModel):
    session_id: str
    function_call_id: str
    answer: str


def _build_input(diff: str, feedback: str | None, target_scope: str | None = None) -> str:
    parts = [f"保育士の修正メモ:\n{diff}"]
    if feedback:
        parts.append(f"\nフィードバック(👍👎):\n{feedback}")
    if target_scope:
        # 保育士が UI で対象書類を選んでいる＝どの書類のための気づきかが確定済み。scope の既定にする
        # （ただし内容的に共通＝全書類向きだと判断したら「共通では?」と提案してよい＝勝手には変えない）。
        parts.append(
            f"\n保育士が指定した対象書類: {target_scope}"
            "（この気づきの反映先。原則この scope をカードの scope の既定にしてください。"
            "ただし内容が明らかに全書類向き＝『共通』が適切だと判断したら、決めつけず ask_caregiver で"
            "『共通（すべての書類）にしますか？』と提案してから決めてください。保育士の選択を勝手に変えない）。"
        )
    parts.append(
        "\n上記がほかの書類・子にも当てはまる**一般化できる勘所**なら、育つ指針カードの追加/改訂案を作り、"
        "既存カードと意味的に競合しないか精査してください。競合があれば該当カードと比較相談し、保育士の決定で"
        "即反映（commit_policy_card）してください。特定の書類・場面に固有で一般化できない気づきなら、"
        "その旨を一言述べて指針は変更しないでください（フィードバックは既に保存済みです）。"
    )
    return "\n".join(parts)


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _normalize_event(event: Any) -> list[dict]:
    """ADK Event → フロントが描けるフラットな {type,...} の列に正規化する。"""
    out: list[dict] = []
    author = getattr(event, "author", None)
    long_running = set(getattr(event, "long_running_tool_ids", None) or [])
    content = getattr(event, "content", None)
    for part in getattr(content, "parts", None) or []:
        text = getattr(part, "text", None)
        fc = getattr(part, "function_call", None)
        fr = getattr(part, "function_response", None)
        if text:
            out.append({"type": "text", "author": author, "text": text})
        if fc is not None:
            out.append(
                {
                    "type": "tool_call",
                    "author": author,
                    "name": getattr(fc, "name", None),
                    "args": dict(getattr(fc, "args", None) or {}),
                    "id": getattr(fc, "id", None),
                    "long_running": getattr(fc, "id", None) in long_running,
                }
            )
        if fr is not None:
            out.append(
                {
                    "type": "tool_result",
                    "author": author,
                    "name": getattr(fr, "name", None),
                    "id": getattr(fr, "id", None),
                    "result": getattr(fr, "response", None),
                }
            )
    return out


async def _stream_run(runner: Any, session_id: str, message: types.Content, improve_sid: str):
    """run_async を回し、各イベントを SSE 化して流す。ask_caregiver で停止したら needs_input を出す。"""
    pending: dict | None = None  # 競合二択などで保留中の質問（HITL）
    try:
        async for event in runner.run_async(
            user_id=_USER_ID, session_id=session_id, new_message=message
        ):
            for item in _normalize_event(event):
                if item["type"] == "tool_call" and item.get("long_running"):
                    args = item.get("args") or {}
                    pending = {
                        "type": "needs_input",
                        "session_id": improve_sid,
                        "function_call_id": item.get("id"),
                        "name": item.get("name"),
                        "question": args.get("question"),
                        "choices": args.get("choices"),
                    }
                yield _sse(item)
    except Exception as e:  # noqa: BLE001  creds 未設定など。降格して UI に正直に出す。
        yield _sse({"type": "error", "detail": f"{type(e).__name__}: {e}"})
        return

    if pending is not None:
        yield _sse(pending)
        return

    final = await runner.session_service.get_session(
        app_name=_APP_NAME, user_id=_USER_ID, session_id=session_id
    )
    _SESSIONS.pop(improve_sid, None)
    yield _sse({"type": "done", "policy_change": (final.state or {}).get("policy_change")})


def register_improver_route(app: FastAPI) -> None:
    @app.post("/api/improve")
    async def improve(req: ImproveRequest) -> StreamingResponse:
        from google.adk.runners import InMemoryRunner

        runner = InMemoryRunner(agent=build_improver_agent(), app_name=_APP_NAME)
        session = await runner.session_service.create_session(app_name=_APP_NAME, user_id=_USER_ID)
        improve_sid = req.session_id or session.id
        _SESSIONS[improve_sid] = (runner, session.id)
        message = types.Content(
            role="user",
            parts=[types.Part(text=_build_input(req.diff, req.feedback, req.target_scope))],
        )
        return StreamingResponse(
            _stream_run(runner, session.id, message, improve_sid),
            media_type="text/event-stream",
        )

    @app.post("/api/improve/resume")
    async def improve_resume(req: ImproveResumeRequest) -> StreamingResponse:
        entry = _SESSIONS.get(req.session_id)
        if entry is None:
            return StreamingResponse(
                iter([_sse({"type": "error", "detail": "セッションが見つかりません（期限切れ）"})]),
                media_type="text/event-stream",
            )
        runner, adk_session_id = entry
        # 保留中の ask_caregiver に function_response を返して invocation を再開する。
        message = types.Content(
            role="user",
            parts=[
                types.Part(
                    function_response=types.FunctionResponse(
                        id=req.function_call_id,
                        name="ask_caregiver",
                        response={"answer": req.answer, "status": "answered"},
                    )
                )
            ],
        )
        return StreamingResponse(
            _stream_run(runner, adk_session_id, message, req.session_id),
            media_type="text/event-stream",
        )
