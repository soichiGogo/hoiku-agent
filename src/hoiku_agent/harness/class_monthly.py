"""harness：クラス月案パイプラインの順序と型の保証（§3/§10/§18）。

依存モデル 2026-07 の候補3系統（クラス児童の保育経過記録、過去のクラス月案、経過記録に未反映の
日誌）は scripts/web が既存 state key に seed する。author が reference_policy に基づき fetch_reference を
選択すると、harness.reference が既存 aggregate と児童別境界を使って決定的に取得する。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from google.adk.agents import SequentialAgent

from ..agents import build_class_monthly_author_agent
from .pipeline import FinalizeAgent, build_authoring_loop, persist_visit_to_memory

if TYPE_CHECKING:
    from google.adk.models import BaseLlm


def build_class_monthly_pipeline(
    author_model: str | BaseLlm | None = None,
    reviewer_model: str | BaseLlm | None = None,
) -> SequentialAgent:
    """クラス月案を作成・レビューし、ClassMonthlyPlan の型を確定する（§18）。"""
    return SequentialAgent(
        name="class_monthly_pipeline",
        sub_agents=[
            build_authoring_loop(build_class_monthly_author_agent(author_model), reviewer_model),
            FinalizeAgent(name="finalize", kind="class_monthly"),
        ],
        after_agent_callback=persist_visit_to_memory,
    )
