"""harness：個別月案パイプラインの順序と型の保証（§3/§4/§10）。

前月日誌は呼び出し側が session state ``prev_month_entries`` に候補として seed する。参照本文を固定で
注入せず、月案 author が reference_policy の既定を踏まえて ``fetch_reference(prev_month_diaries)`` を
選択した時点で ``harness.reference`` が決定的に集計する。pipeline は authoring_loop→finalize のみを組む。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from google.adk.agents import SequentialAgent

from ..agents import build_monthly_author_agent
from .pipeline import FinalizeAgent, build_authoring_loop, persist_visit_to_memory

if TYPE_CHECKING:
    from google.adk.models import BaseLlm


def build_monthly_pipeline(
    author_model: str | BaseLlm | None = None,
    reviewer_model: str | BaseLlm | None = None,
) -> SequentialAgent:
    """個別月案を作成・レビューし、MonthlyPlan の型を確定する（§3/§4/§10）。"""
    return SequentialAgent(
        name="monthly_plan_pipeline",
        sub_agents=[
            build_authoring_loop(build_monthly_author_agent(author_model), reviewer_model),
            FinalizeAgent(name="finalize", kind="monthly"),
        ],
        after_agent_callback=persist_visit_to_memory,
    )
