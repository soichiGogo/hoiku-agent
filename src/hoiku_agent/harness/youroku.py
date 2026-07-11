"""harness：保育要録パイプラインの順序と型の保証（§19・L4）。

それまでの保育経過記録は session state ``record_entries`` に候補として seed する。要録 author が
reference_policy に基づき ``fetch_reference(prev_child_records)`` を選択した時点で、harness.reference が
``aggregate.child_record_digest`` により決定的に取得する。日誌は候補へ加えない。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from google.adk.agents import SequentialAgent

from ..agents import build_nursery_record_author_agent
from .pipeline import FinalizeAgent, build_authoring_loop, persist_visit_to_memory

if TYPE_CHECKING:
    from google.adk.models import BaseLlm


def build_nursery_record_pipeline(
    author_model: str | BaseLlm | None = None,
    reviewer_model: str | BaseLlm | None = None,
) -> SequentialAgent:
    """保育要録を作成・レビューし、NurseryRecord の型を確定する（§19・L4）。"""
    return SequentialAgent(
        name="nursery_record_pipeline",
        sub_agents=[
            build_authoring_loop(build_nursery_record_author_agent(author_model), reviewer_model),
            FinalizeAgent(name="finalize", kind="nursery_record"),
        ],
        after_agent_callback=persist_visit_to_memory,
    )
