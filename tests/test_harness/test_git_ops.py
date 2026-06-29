"""harness.git_ops（育つ指針 JSON の証拠 commit）の単体テスト（LLM 非依存）。

設計コンテキスト §8/§16：カードストア JSON の git 証拠 commit は決定的・降格付き。dry_run（既定）は
実 git を叩かず計画を返す（subprocess の実行系はここでは叩かない）。
"""

from __future__ import annotations

from hoiku_agent.harness import commit_policy_book


def test_commit_policy_book_dry_run_does_not_touch_git(tmp_path):
    """dry_run（既定）は実 commit をせず計画を返す。"""
    (tmp_path / "knowledge").mkdir()
    (tmp_path / "knowledge" / "文書作成指針.json").write_text("{}", encoding="utf-8")
    result = commit_policy_book(title="policy: 共通 を更新", repo_root=tmp_path, dry_run=True)
    assert result["status"] == "dry_run"
    assert result["path"].endswith("文書作成指針.json")
    assert result["branch"] == "improver/policy-update"


def test_commit_policy_book_missing_json_degrades(tmp_path):
    """指針 JSON が無ければ raise せず error status で降格する。"""
    result = commit_policy_book(title="x", repo_root=tmp_path, dry_run=False)
    assert result["status"] == "error"
