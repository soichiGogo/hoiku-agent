"""harness.git_ops の構造化編集（純関数）の単体テスト（LLM 非依存）。

設計コンテキスト §16：指針の構造化編集の適用は決定的ロジックとして pytest 必須。
git/gh の subprocess（open_pr 実行系）はここでは叩かない（dry_run のみ別途）。
"""

from __future__ import annotations

import pytest

from hoiku_agent.harness import apply_structured_edit, list_section_bullets
from hoiku_agent.harness.git_ops import open_pr

_SAMPLE = """\
# 文書作成指針

## 書類別の勘所

### 保育日誌
- 既存の項目A
- 既存の項目B

### 月案 / 週案 / 日案
- 月案の項目

## 変更履歴
- 初版
"""


@pytest.fixture()
def guideline(tmp_path):
    path = tmp_path / "文書作成指針.md"
    path.write_text(_SAMPLE, encoding="utf-8")
    return path


def _edit(op, after="", before="", heading="### 保育日誌"):
    return {
        "target_heading": heading,
        "op": op,
        "before": before,
        "after": after,
        "rationale": "テスト",
    }


def test_add_appends_bullet_to_section(guideline):
    out = apply_structured_edit(_edit("add", after="新しい勘所"), path=guideline)
    section = out.split("### 保育日誌")[1].split("###")[0]
    assert "- 新しい勘所" in section
    # 隣のセクションを侵食しない
    assert "- 月案の項目" in out


def test_add_accepts_heading_path_notation(guideline):
    """'### 書類別の勘所 > 保育日誌' のパス表記でも末尾セグメントで解決する。"""
    out = apply_structured_edit(
        _edit("add", after="X", heading="### 書類別の勘所 > 保育日誌"), path=guideline
    )
    assert "- X" in out.split("### 保育日誌")[1].split("###")[0]


def test_modify_replaces_matching_bullet(guideline):
    out = apply_structured_edit(
        _edit("modify", before="既存の項目A", after="改訂A"), path=guideline
    )
    assert "既存の項目A" not in out
    assert "- 改訂A" in out


def test_remove_deletes_matching_bullet(guideline):
    out = apply_structured_edit(_edit("remove", before="既存の項目B"), path=guideline)
    assert "既存の項目B" not in out
    assert "既存の項目A" in out


def test_missing_heading_raises(guideline):
    with pytest.raises(ValueError):
        apply_structured_edit(_edit("add", after="X", heading="### 存在しない"), path=guideline)


def test_modify_missing_before_raises(guideline):
    with pytest.raises(ValueError):
        apply_structured_edit(_edit("modify", before="無い項目", after="Y"), path=guideline)


def test_list_section_bullets(guideline):
    assert list_section_bullets("### 保育日誌", path=guideline) == ["既存の項目A", "既存の項目B"]
    assert list_section_bullets("### 存在しない", path=guideline) == []


_NESTED = """\
## 勘所

### 保育日誌
- 既存

#### 補足メモ
- ネスト項目

### 月案
- m
"""

_DUP = """\
## アンチパターン
### 保育日誌
- a項目

## 書類別の勘所
### 保育日誌
- b項目
"""


def test_add_inserts_into_direct_content_not_nested_subsection(tmp_path):
    path = tmp_path / "g.md"
    path.write_text(_NESTED, encoding="utf-8")
    out = apply_structured_edit(_edit("add", after="新項目"), path=path)
    # 新項目は 保育日誌 直下（#### 補足メモ の前）に入る
    direct = out.split("### 保育日誌")[1].split("#### 補足メモ")[0]
    assert "- 新項目" in direct


def test_list_section_bullets_excludes_nested_and_hr(tmp_path):
    path = tmp_path / "g.md"
    path.write_text(
        "### 保育日誌\n- 本物\n---\n- もう一つ\n\n#### 補足\n- ネスト\n### 次\n", encoding="utf-8"
    )
    assert list_section_bullets("### 保育日誌", path=path) == ["本物", "もう一つ"]


def test_ambiguous_heading_raises(tmp_path):
    path = tmp_path / "g.md"
    path.write_text(_DUP, encoding="utf-8")
    with pytest.raises(ValueError):
        apply_structured_edit(_edit("add", after="X", heading="### 保育日誌"), path=path)


def test_path_notation_disambiguates_duplicate_headings(tmp_path):
    path = tmp_path / "g.md"
    path.write_text(_DUP, encoding="utf-8")
    out = apply_structured_edit(
        _edit("add", after="X", heading="## 書類別の勘所 > 保育日誌"), path=path
    )
    # 書類別の勘所 配下にだけ入り、アンチパターン側は触らない
    assert "- X" in out.split("## 書類別の勘所")[1]
    assert "- X" not in out.split("## 書類別の勘所")[0]


def test_open_pr_dry_run_does_not_touch_git(guideline, tmp_path):
    """dry_run（既定）は実 commit/PR をせず計画を返す。"""
    (tmp_path / "knowledge").mkdir()
    (tmp_path / "knowledge" / "文書作成指針.md").write_text(_SAMPLE, encoding="utf-8")
    result = open_pr(
        _edit("add", after="新しい勘所"),
        title="指針更新",
        body="本文",
        repo_root=tmp_path,
        dry_run=True,
    )
    assert result["status"] == "dry_run"
    assert "新しい勘所" in result["preview"]
