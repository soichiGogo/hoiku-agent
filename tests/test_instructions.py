"""参照ポリシーを注入する InstructionProvider の決定論テスト。"""

from __future__ import annotations

import hoiku_agent.agents.instructions as instr
from hoiku_agent.agents.instructions import build_author_instruction, build_review_instruction
from hoiku_agent.harness.policy_store import load_book
from hoiku_agent.schemas import PolicyScope


class _Ctx:
    def __init__(self, state: dict) -> None:
        self.state = state


def test_author_injects_scope_guideline_text():
    """scope の指針カード（参照方針も自然文の1枚として含む）が author instruction にそのまま前置される。"""
    out = build_author_instruction("BASE", PolicyScope.保育経過記録)(_Ctx({}))
    assert (
        "保育経過記録の作成では" in out
    )  # seed の参照方針カード本文（自然文・knowledge/文書作成指針.json）
    assert "【期間の集積" not in out
    assert out.endswith("BASE")


def test_author_reflects_edited_guideline_text(monkeypatch):
    """指針カードの本文を差し替えると author instruction にもそのまま反映される（他カードと同じ自然文編集）。"""
    book = load_book()
    for c in book.cards:
        if c.scope == PolicyScope.保育経過記録:
            c.body = "テスト用の差し替えテキスト：期間日誌だけを参照する。"
    monkeypatch.setattr(instr, "load_book", lambda: book)
    out = build_author_instruction("BASE", PolicyScope.保育経過記録)(_Ctx({}))
    assert "テスト用の差し替えテキスト：期間日誌だけを参照する。" in out


def test_review_injects_reference_manifest():
    state = {
        "doc_type": "保育要録",
        "reference_manifest": [{"source": "prev_child_records", "count": 2, "empty": False}],
    }
    out = build_review_instruction("REVIEW")(_Ctx(state))
    assert "【参照取得実績】" in out
    assert "prev_child_records: 2件" in out
    assert out.endswith("REVIEW")


def test_review_reports_no_fetch():
    out = build_review_instruction("REVIEW")(_Ctx({"doc_type": "月案"}))
    assert "まだ fetch_reference による取得はありません" in out


def test_store_failure_degrades(monkeypatch):
    monkeypatch.setattr(instr, "load_book", lambda: (_ for _ in ()).throw(RuntimeError()))
    assert build_author_instruction("BASE", PolicyScope.月案)(_Ctx({})) == "BASE"
