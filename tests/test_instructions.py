"""作成AI・レビューAI の InstructionProvider（文書作成指針・集積の前置注入）の決定論テスト。

設計コンテキスト §5/§6/§8/§9。provider は純関数（(ReadonlyContext)->str）で LLM/GCP 非依存に
テストできる。ここでは「指針が prompt 冒頭に前置され base instruction が末尾に来る」「scope で共通＋
当該書類だけに絞る」「集積は state から整形して前置・空なら前置しない」「reviewer は state[doc_type]
から scope 解決」「ストア障害は指針省略へ降格」を固定する。
"""

from __future__ import annotations

import hoiku_agent.agents.instructions as instr
from hoiku_agent.agents.instructions import build_author_instruction, build_review_instruction
from hoiku_agent.harness.aggregate import format_record_digest_for_prompt
from hoiku_agent.schemas.policy import PolicyScope


class _Ctx:
    """ReadonlyContext の最小スタブ（provider は .state だけ読む）。"""

    def __init__(self, state: dict) -> None:
        self.state = state


def _digest(note_count: int = 3) -> dict:
    return {
        "はるとくん": {
            "note_count": note_count,
            "tag_freq": {"健やかに伸び伸びと育つ": 2},
            "observed_states": ["砂場で感触を確かめていた"],
        }
    }


# ──────────────────────────── author provider ────────────────────────────


def test_author_provider_prepends_policy_then_base():
    """指針（共通＋保育日誌）が冒頭・base instruction が末尾（与件→手順の順）。他書類の節は出さない。"""
    prov = build_author_instruction("BASE-INSTRUCTION", PolicyScope.保育日誌)
    out = prov(_Ctx({}))
    assert out.startswith("# 文書作成指針")
    assert "## 共通ルール（園・書類横断）" in out
    assert "### 保育日誌" in out
    assert "### 月案 / 週案 / 日案" not in out  # 絞り込み（当該書類のみ）
    assert out.rstrip().endswith("BASE-INSTRUCTION")


def test_author_provider_injects_digest_when_present():
    """月案 author は state["prev_month_digest"] を format して指針と base の間に前置する。"""
    prov = build_author_instruction(
        "BASE", PolicyScope.月案, digest_key="prev_month_digest", digest_label="前月"
    )
    out = prov(_Ctx({"prev_month_digest": _digest()}))
    assert "### 月案 / 週案 / 日案" in out  # 月案 scope の指針
    assert "【前月の集積" in out  # format_digest_for_prompt の見出し
    assert "はるとくん" in out
    assert out.rstrip().endswith("BASE")


def test_author_provider_skips_absent_or_empty_digest():
    """集積が無い/空（初回）なら digest は前置しない（指針＋base のみ）。"""
    prov = build_author_instruction(
        "BASE", PolicyScope.月案, digest_key="prev_month_digest", digest_label="前月"
    )
    out_absent = prov(_Ctx({}))
    out_empty = prov(_Ctx({"prev_month_digest": {}}))
    for out in (out_absent, out_empty):
        assert "【前月の集積" not in out
        assert out.rstrip().endswith("BASE")


def _record_digest() -> dict:
    return {
        "はるとくん": {
            "record_count": 3,
            "periods": ["2026-04〜2026-07", "2026-08〜2026-11", "2026-12〜2027-03"],
            "tag_freq": {"人間関係": 2, "健康": 1},
            "development": ["（2026-04〜2026-07）友だちと関わって遊んだ"],
            "overall_notes": ["（2026-04〜2026-07）自分を発揮し始めた"],
            "care_notes": [],
            "next_aims": [],
        }
    }


def test_author_provider_uses_record_formatter_for_youroku():
    """保育要録 author は record_digest を format_record_digest_for_prompt で前置する（L4＝保育経過記録集積）。"""
    prov = build_author_instruction(
        "BASE",
        PolicyScope.保育要録,
        digest_key="record_digest",
        digest_label="最終年度",
        digest_formatter=format_record_digest_for_prompt,
    )
    out = prov(_Ctx({"record_digest": _record_digest()}))
    assert "### 保育要録（保育所児童保育要録・小学校引継ぎ）" in out  # 要録 scope の指針
    assert "【最終年度の保育経過記録 集積" in out  # format_record_digest_for_prompt の見出し
    assert "はるとくん" in out and "友だちと関わって遊んだ" in out
    assert out.rstrip().endswith("BASE")


# ──────────────────────────── review provider ────────────────────────────


def test_review_provider_resolves_scope_from_doc_type():
    """reviewer は書類共用＝state["doc_type"] で scope（＋集積）を解決する。"""
    prov = build_review_instruction("REVIEW-BASE")
    out = prov(_Ctx({"doc_type": "保育経過記録", "period_digest": _digest()}))
    assert "### 保育経過記録（期ごと）" in out
    assert "### 月案 / 週案 / 日案" not in out
    assert "【期間の集積" in out  # 保育経過記録は period_digest を前置
    assert out.rstrip().endswith("REVIEW-BASE")


def test_review_provider_defaults_to_class_monthly_when_doc_type_unset():
    """doc_type 未設定（既定＝クラス月案＝router）なら月案 scope を前置する（保育日誌は AI 生成退役）。"""
    prov = build_review_instruction("R")
    out = prov(_Ctx({}))
    assert "### 月案 / 週案 / 日案" in out


def test_review_provider_resolves_youroku_scope_and_record_digest():
    """reviewer は doc_type=保育要録 で要録 scope＋record_digest（要録 formatter）を前置する（L4）。"""
    prov = build_review_instruction("REVIEW-BASE")
    out = prov(_Ctx({"doc_type": "保育要録", "record_digest": _record_digest()}))
    assert "### 保育要録（保育所児童保育要録・小学校引継ぎ）" in out
    assert "【最終年度の保育経過記録 集積" in out  # 要録は record_digest を要録 formatter で前置
    assert out.rstrip().endswith("REVIEW-BASE")


# ──────────────────────────── 降格 ────────────────────────────


def test_provider_degrades_when_store_raises(monkeypatch):
    """指針ストアが壊れ/未整備でも provider は落ちず指針を省略して base だけ返す（生成を止めない＝§9）。"""

    def _boom(*a, **k):
        raise RuntimeError("store unreachable")

    monkeypatch.setattr(instr, "load_book", _boom)
    prov = build_author_instruction("BASE-ONLY", PolicyScope.保育日誌)
    assert prov(_Ctx({})) == "BASE-ONLY"
