"""harness.pipeline の APPROVED 早期終了判定（決定的）の単体テスト。

設計コンテキスト §7/§16：APPROVED 早期終了の "判定" は harness の決定的ロジック。
"""

from __future__ import annotations

from hoiku_agent.harness.pipeline import build_document_pipeline, is_approved


def test_is_approved_first_line_verdict():
    assert is_approved("APPROVED") is True
    assert is_approved("APPROVED（問題なし）") is True
    assert is_approved("**APPROVED**\n（特に指摘なし）") is True


def test_is_approved_false_on_findings():
    # 1行目が NEEDS_REVISION / 指摘本文なら未承認
    assert is_approved("NEEDS_REVISION\ncriterion: 指針整合 / severity: must_fix") is False
    assert is_approved("criterion: ... / message: この記述は approved とは言えない") is False


def test_is_approved_false_on_negation():
    # 散文の否定形で誤って早期終了しない（部分一致の脆弱性の回帰防止）
    assert is_approved("NOT APPROVED") is False
    assert is_approved("未APPROVED：以下を要修正") is False


def test_is_approved_handles_non_string():
    assert is_approved(None) is False
    assert is_approved({"review": "APPROVED"}) is False


def test_pipeline_structure():
    """root_agent の段構成（author→review_loop→finalize、loop 内は reviewer→approval_gate）。"""
    pipeline = build_document_pipeline()
    assert [a.name for a in pipeline.sub_agents] == ["author", "review_loop", "finalize"]
    loop = pipeline.sub_agents[1]
    assert [a.name for a in loop.sub_agents] == ["reviewer", "approval_gate"]
