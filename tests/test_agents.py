"""作成AI／レビューAI のツール配線（B方針＝§9）を固定する LLM 非依存テスト。

設計コンテキスト §6/§9：継続把握は recall_child_history（Memory Bank）に一本化し、過去書類アーカイブ
search_past_documents は agent に配線しない（B方針）。配線意図を回帰（recall を落とす／
search_past_documents を再配線する）から守る。creds 不要・LLM 非依存。
"""

from __future__ import annotations

import pytest


def _tool_names(agent) -> set[str]:
    # tools は素の関数（__name__）と LongRunningFunctionTool（.name）が混在する
    return {getattr(t, "__name__", None) or getattr(t, "name", "") for t in agent.tools}


def test_continuity_tool_wiring_author_and_reviewer():
    """継続把握は recall_child_history に一本化、search_past_documents は agent から外す（§9・B）。"""
    pytest.importorskip("google.adk", reason="google-adk 未インストール（uv sync で有効化）")
    from hoiku_agent.agents.author_agent import build_author_agent
    from hoiku_agent.agents.review_agent import build_review_agent

    for build in (build_author_agent, build_review_agent):
        names = _tool_names(build())
        assert "recall_child_history" in names, names
        assert "search_past_documents" not in names, names
