"""harness.pipeline の APPROVED 早期終了判定（決定的）の単体テスト。

設計コンテキスト §7/§16：APPROVED 早期終了の "判定" は harness の決定的ロジック。
"""

from __future__ import annotations

from hoiku_agent.harness.child_record import build_child_record_pipeline
from hoiku_agent.harness.pipeline import is_approved


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
    """共用の段構成（…→authoring_loop→finalize、loop 内は author→reviewer→approval_gate）。

    保育日誌の AI 生成パイプラインは退役したので、共用機構は保育経過記録パイプラインで検証する。
    NEEDS_REVISION で作成AIが再作成できるよう author をレビュー巡回に**含める**（旧構成は author を
    ループ外に置き再作成が起きなかった＝本変更の回帰防止）。finalize は末尾・prep 段が先頭（§5/§19）。
    """
    pipeline = build_child_record_pipeline()
    names = [a.name for a in pipeline.sub_agents]
    assert names[-1] == "finalize" and "authoring_loop" in names
    loop = next(a for a in pipeline.sub_agents if a.name == "authoring_loop")
    # loop 内は [作成AI, reviewer, approval_gate]（作成AI を巡回に含める＝再作成保証）
    loop_names = [a.name for a in loop.sub_agents]
    assert loop_names[-2:] == ["reviewer", "approval_gate"]
    assert loop_names[0].endswith("author")
