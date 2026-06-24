"""改善エージェント（二階＝まわす本丸・責務③）。

設計コンテキスト §8。修正差分→指針更新を構造化編集で自走提案し、競合は保育士に二択で確定、
branch/PR→CI 評価ゲート→緑なら auto-merge→再デプロイ→還元 のループを回す。

置き場の確定（§8）：一階の agent.py（root_agent）は document_pipeline 固定なので、二階は
ここに分離する。**root_agent には組み込まない・自動起動しない**。v0 は手動起動（別エントリ：
`adk run` でモジュール指定、または専用スクリプト）。

単一エージェント＋少数ツール（多層化しない＝§4）。
"""

from __future__ import annotations

from google.adk.agents import LlmAgent

from ..config import settings
from .prompts import IMPROVER_INSTRUCTION
from .tools import ask_caregiver, open_pr, propose_policy_change, run_eval


def build_improver_agent() -> LlmAgent:
    """改善エージェント（単一 LlmAgent）を構築して返す。root_agent とは別エントリ（§8）。"""
    return LlmAgent(
        name="improver",
        model=settings.gemini_model,
        instruction=IMPROVER_INSTRUCTION,
        tools=[propose_policy_change, run_eval, ask_caregiver, open_pr],
        output_key="policy_change",
    )
