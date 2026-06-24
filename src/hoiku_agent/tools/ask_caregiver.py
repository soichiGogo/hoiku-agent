"""ツール：保育士に質問する（HITL／人への escalate）。

設計コンテキスト §6 ツール表（ask_caregiver）/ §6末「HITL の実装機構」。作成AIは致命的不足を
推測で埋めず保育士に質問する（負荷を上げない・重要な点に絞る）。improver も既存指針と競合した
ときに同じ「人に訊く」口で二択を仰ぐ（§8）。最終的な応答主体・確定は人（§7）。

v0 は ADK の同期ツールとして実装し、`adk run`/`adk web` の対話ターンで回答を受ける。回答は
output_key で state["caregiver_answer"] に格納し、後続の再起案が読む（§6）。長期中断
（pause-resume / long-running tool）の要否は未決（着手時に公式 docs で確認＝§18）。

TODO(設計):
- ADK 同期ツールとしての受け答え配線（output_key→state）。
- 二択（competition 解消）用の選択肢提示インターフェース（improver と共用）。
"""

from __future__ import annotations


def ask_caregiver(question: str, choices: list[str] | None = None) -> str:
    """保育士に質問し、回答（文字列）を返す。choices があれば二択等の選択を促す。

    Args:
        question: 保育士への質問（致命的不足のみ・簡潔に）。
        choices: 競合解消などで二択を仰ぐときの選択肢（任意）。

    Returns:
        保育士の回答。
    """
    # TODO(設計): ADK 同期ツールで対話ターンの回答を受け取り state["caregiver_answer"] に格納する。
    # v0 は他スタブと同様に無害なプレースホルダを返し、稼働中パイプラインを落とさない
    # （root_agent に配線済みのため raise すると adk run/web が落ちる）。
    return "（保育士の回答待ち：HITL 未配線。設計コンテキスト §6 で実装する）"
