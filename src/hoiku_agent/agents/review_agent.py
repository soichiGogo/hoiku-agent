"""レビューAI（別視点の評価＝二軸の片方・責務②）。

設計コンテキスト §7：作成AIとは別視点の Evaluator として巡回（Generate→Evaluate→Revise）。
レビューは作成の各段階に散らさず最終段階で一括評価する。観点は育つ指針から取る。
最終OK（確定）は必ず保育士＝HITL。AIは「保育士が編集・確定する下書き／指摘」に徹する。

巡回（LoopAgent）と APPROVED 早期終了の "制御" は harness/pipeline.py 側（決定的）。本モジュールは
reviewer 単体（指摘の生成）を返す。指摘結果は state["review"] に格納。
"""

from __future__ import annotations

from google.adk.agents import LlmAgent

from ..config import settings
from ..tools import read_policy, search_guideline, search_records
from .prompts import REVIEW_INSTRUCTION


def build_review_agent() -> LlmAgent:
    """レビューAI（単一 LlmAgent）を構築して返す。巡回制御は harness 側。"""
    return LlmAgent(
        name="reviewer",
        model=settings.gemini_model,
        instruction=REVIEW_INSTRUCTION,
        # search_records は前月連続性の照合に使う（§7 の観点を実際に検証できるように）
        tools=[read_policy, search_guideline, search_records],
        output_key="review",  # 指摘結果を state["review"] に格納
    )
