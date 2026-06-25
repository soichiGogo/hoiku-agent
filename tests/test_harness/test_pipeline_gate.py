"""harness.pipeline の APPROVED 早期終了判定（決定的）の単体テスト。

設計コンテキスト §7/§16：APPROVED 早期終了の "判定" は harness の決定的ロジック。
"""

from __future__ import annotations

from hoiku_agent.harness.pipeline import build_document_pipeline, is_approved


def test_is_approved_detects_token():
    assert is_approved("APPROVED") is True
    assert is_approved("総評: approved（問題なし）") is True


def test_is_approved_false_on_findings():
    assert is_approved("criterion: 指針整合 / severity: must_fix / message: ...") is False


def test_is_approved_handles_non_string():
    assert is_approved(None) is False
    assert is_approved({"review": "APPROVED"}) is False


def test_pipeline_structure():
    """root_agent の段構成（author→review_loop→finalize、loop 内は reviewer→approval_gate）。"""
    pipeline = build_document_pipeline()
    assert [a.name for a in pipeline.sub_agents] == ["author", "review_loop", "finalize"]
    loop = pipeline.sub_agents[1]
    assert [a.name for a in loop.sub_agents] == ["reviewer", "approval_gate"]
