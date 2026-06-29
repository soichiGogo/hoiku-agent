"""改善エージェント（二階＝まわす本丸・責務③）。

設計コンテキスト §8。保育士の修正メモ→育つ指針カードの更新を自走提案し、既存カードとの**意味的競合**を
精査、競合があれば保育士に該当カードを提示して比較相談し、**保育士の決定で即反映**（add／supersede）する
ループを回す（番人＝意味的競合精査＋保育士決定。評価ゲートは取り込みフローから外す＝§8/§12）。

置き場の確定（§8）：一階の agent.py（root_agent）は document_pipeline 固定なので、二階は
ここに分離する。**root_agent には組み込まない・自動起動しない**。手動起動（別エントリ：専用スクリプト
／Web の SSE 駆動）。単一エージェント＋少数ツール（多層化しない＝§4）。
"""

from __future__ import annotations

from google.adk.agents import LlmAgent

from ..models import build_model
from .prompts import IMPROVER_INSTRUCTION
from .tools import ask_caregiver, commit_policy_card, propose_policy_card, read_policy_cards


def build_improver_agent() -> LlmAgent:
    """改善エージェント（単一 LlmAgent）を構築して返す。root_agent とは別エントリ（§8）。"""
    return LlmAgent(
        name="improver",
        model=build_model(),
        instruction=IMPROVER_INSTRUCTION,
        tools=[read_policy_cards, propose_policy_card, ask_caregiver, commit_policy_card],
        output_key="policy_change",
    )
