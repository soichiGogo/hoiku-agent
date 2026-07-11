"""author/reviewer が構造化された参照候補を取得する薄い ADK tool。"""

from __future__ import annotations

from google.adk.tools import ToolContext

from ..harness.reference import fetch_reference_from_state
from ..schemas import ReferenceSource


def fetch_reference(
    source: ReferenceSource,
    tool_context: ToolContext,
) -> dict:
    """指定された参照種別を session state の候補から取得する。識別子や検索語は受け取らない。"""
    return fetch_reference_from_state(tool_context.state, source)
