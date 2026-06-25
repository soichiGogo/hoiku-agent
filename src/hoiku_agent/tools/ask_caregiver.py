"""ツール：保育士に質問する（HITL／人への escalate）。

設計コンテキスト §6 ツール表（ask_caregiver）/ §6末「HITL の実装機構」。作成AIは致命的不足を
推測で埋めず保育士に質問する（負荷を上げない・重要な点に絞る）。improver も既存指針と競合した
ときに同じ「人に訊く」口で二択を仰ぐ（§8）。最終的な応答主体・確定は人（§7）。

実装（v0 確定）：ADK の **LongRunningFunctionTool** で実装する。これは ADK が用意する HITL の
標準プリミティブ（組込みの get_user_choice も同型）。呼び出すと「保留（pending）」を即時返し、実際の
保育士の回答はフレームワークが function_call_id 経由で後から差し込む。`adk web` の対話で人が応答でき、
長期中断（保育士が後で答える＝§6 未決だった点）も同じ仕組みで吸収できる。choices で二択（競合解消）。

注: 公開シンボル `ask_caregiver`（tools/__init__）は **このツールインスタンス** を指す。関数本体は
下記 `ask_caregiver` 関数で、ツール名はその __name__ から "ask_caregiver" になる。
"""

from __future__ import annotations

from google.adk.tools import LongRunningFunctionTool


def ask_caregiver(question: str, choices: list[str] | None = None) -> dict:
    """保育士に質問し回答を仰ぐ（HITL）。choices があれば選択（二択等）を促す。

    Args:
        question: 保育士への質問（致命的不足のみ・簡潔に）。
        choices: 競合解消などで選択肢を提示するとき（任意）。

    Returns:
        保留（pending）ペイロード。実際の回答は LongRunningFunctionTool として後から差し込まれる。
    """
    payload: dict = {
        "status": "pending",
        "question": question,
        "note": "保育士の回答を待っています（HITL）。回答が確定するまで推測で進めないこと。",
    }
    if choices:
        payload["choices"] = choices
    return payload


# 公開シンボル＝ツールインスタンス（ツール名は func.__name__ = "ask_caregiver"）。
ask_caregiver_tool = LongRunningFunctionTool(func=ask_caregiver)
