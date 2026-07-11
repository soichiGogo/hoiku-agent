"""harness：保育経過記録パイプラインの順序と型の保証（§19・L3）。

該当期間の日誌と前回までの保育経過記録は、それぞれ ``period_entries`` と ``prev_record_entries`` に
候補として seed する。author が reference_policy に基づき fetch_reference を選択した時点で
``harness.reference`` が決定的に集計する。作成対象期を除く規則と workspace 境界は seed 側に残す。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from google.adk.agents import SequentialAgent

from ..agents import build_child_record_author_agent
from .pipeline import FinalizeAgent, build_authoring_loop, persist_visit_to_memory

if TYPE_CHECKING:
    from google.adk.models import BaseLlm


def build_child_record_pipeline(
    author_model: str | BaseLlm | None = None,
    reviewer_model: str | BaseLlm | None = None,
) -> SequentialAgent:
    """保育経過記録を作成・レビューし、ChildRecord の型を確定する（§19・L3）。"""
    return SequentialAgent(
        name="child_record_pipeline",
        sub_agents=[
            build_authoring_loop(build_child_record_author_agent(author_model), reviewer_model),
            FinalizeAgent(name="finalize", kind="child_record"),
        ],
        after_agent_callback=persist_visit_to_memory,
    )
