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


def test_improver_reference_tools_and_confirmation_gate_are_wired():
    """参照変更は read→propose→ask→commit を同じ単一エージェントで回す。"""
    pytest.importorskip("google.adk", reason="google-adk 未インストール（uv sync で有効化）")
    from hoiku_agent.improver.improver_agent import build_improver_agent
    from hoiku_agent.improver.prompts import IMPROVER_INSTRUCTION

    names = _tool_names(build_improver_agent())
    assert {
        "read_reference_policy",
        "propose_reference_update",
        "ask_caregiver",
        "commit_reference_update",
    } <= names
    assert "同意前、拒否、取消時は絶対に commit しない" in IMPROVER_INSTRUCTION
    assert IMPROVER_INSTRUCTION.index("`ask_caregiver`") < IMPROVER_INSTRUCTION.index(
        "`commit_reference_update`"
    )


def test_continuity_tool_wiring_author_and_reviewer():
    """継続把握は recall_child_history に一本化、search_past_documents は agent から外す（§9・B）。"""
    pytest.importorskip("google.adk", reason="google-adk 未インストール（uv sync で有効化）")
    # 保育日誌の作成AI（build_author_agent）は退役（手入力＝AI 生成を通さない）ため対象外。
    from hoiku_agent.agents.child_record_author_agent import build_child_record_author_agent
    from hoiku_agent.agents.monthly_author_agent import build_monthly_author_agent
    from hoiku_agent.agents.review_agent import build_review_agent

    for build in (
        build_monthly_author_agent,
        build_child_record_author_agent,
        build_review_agent,
    ):
        names = _tool_names(build())
        assert "recall_child_history" in names, names
        assert "search_past_documents" not in names, names


def test_child_record_author_shape():
    """保育経過記録 author は単一 LlmAgent・output_key="draft"（日誌/月案と共通の受け渡し＝§6/§19）。"""
    pytest.importorskip("google.adk", reason="google-adk 未インストール（uv sync で有効化）")
    from hoiku_agent.agents.child_record_author_agent import build_child_record_author_agent

    agent = build_child_record_author_agent()
    assert agent.name == "child_record_author"
    assert agent.output_key == "draft"
    # 自己点検ツール（validate_fields＝DiaryEntry 用）は配線しない（確定検査は harness が末尾実行）。
    assert "validate_fields" not in _tool_names(agent)
