"""improver（二階）の決定的ロジックの単体テスト（LLM 非依存）。

設計コンテキスト §8/§16：構造化編集の提案・競合検出（文字列一致）・ゲート呼び出しの降格を検証。
"""

from __future__ import annotations

from hoiku_agent.improver.tools import open_pr, propose_policy_change, run_eval


def test_propose_no_conflict_for_new_bullet():
    result = propose_policy_change("### 保育日誌", "感触遊びは感触語と表情を併記する")
    assert result["has_conflict"] is False
    assert result["edit"]["op"] == "add"
    assert result["edit"]["after"] == "感触遊びは感触語と表情を併記する"


def test_propose_detects_conflict_with_existing_bullet():
    """既存のプレースホルダ項目を包含する提案は競合として検出される。"""
    result = propose_policy_change("### 保育日誌", "ヒアリングで収集して追記")
    assert result["has_conflict"] is True
    assert result["conflicts"]


def test_run_eval_degrades_without_credentials():
    """ケースはあるが資格情報が無い環境では passed=None（判定不能）で降格する。"""
    result = run_eval()
    assert result["passed"] in (None, True)
    assert "status" in result


def test_open_pr_dry_run_default():
    result = open_pr("### 保育日誌", "新しい勘所", "指針更新", "本文")
    assert result["status"] == "dry_run"
