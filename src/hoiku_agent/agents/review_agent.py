"""レビューAI（別視点の評価＝二軸の片方・責務②）。

設計コンテキスト §7：作成AIとは別視点の Evaluator として巡回（Generate→Evaluate→Revise）。
レビューは作成の各段階に散らさず最終段階で一括評価する。観点は育つ指針から取る。
最終OK（確定）は必ず保育士＝HITL。AIは「保育士が編集・確定する下書き／指摘」に徹する。

巡回（LoopAgent）と APPROVED 早期終了の "制御" は harness/pipeline.py 側（決定的）。本モジュールは
reviewer 単体（指摘の生成）を返す。指摘結果は state["review"] に格納。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from google.adk.agents import LlmAgent

from ..models import build_model
from ..tools import fetch_reference, recall_child_history, search_guideline
from .instructions import build_review_instruction
from .prompts import REVIEW_INSTRUCTION

if TYPE_CHECKING:
    from google.adk.models import BaseLlm


def build_review_agent(model: str | BaseLlm | None = None) -> LlmAgent:
    """レビューAI（単一 LlmAgent）を構築して返す。巡回制御は harness 側。

    Args:
        model: 使用するモデル。既定（None）は build_model()（settings.gemini_model を
            model_location＝global に固定した Gemini。§11／models.py）。
            決定論E2E では FakeLlm 等の BaseLlm を注入する差込口（§16）。本番は引数なしで不変。
    """
    return LlmAgent(
        name="reviewer",
        model=model if model is not None else build_model(),
        # scope 別の指針・参照既定と author の reference_manifest を提示する（§5）。
        instruction=build_review_instruction(REVIEW_INSTRUCTION),
        # recall_child_history は前月連続性の照合に使う（その子の前回までの像と矛盾しないか＝§7）
        tools=[fetch_reference, search_guideline, recall_child_history],
        output_key="review",  # 指摘結果を state["review"] に格納
    )
