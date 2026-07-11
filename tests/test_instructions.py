"""参照ポリシーを注入する InstructionProvider の決定論テスト。"""

from __future__ import annotations

import hoiku_agent.agents.instructions as instr
from hoiku_agent.agents.instructions import build_author_instruction, build_review_instruction
from hoiku_agent.harness.policy_store import load_book
from hoiku_agent.schemas import PolicyScope, ReferenceSource


class _Ctx:
    def __init__(self, state: dict) -> None:
        self.state = state


def test_author_injects_enabled_reference_defaults_without_digest():
    out = build_author_instruction("BASE", PolicyScope.保育経過記録)(_Ctx({}))
    assert "period_diary" in out
    assert "prev_child_records" in out
    assert "fetch_reference" in out
    assert "【期間の集積" not in out
    assert out.endswith("BASE")


def test_disabled_reference_disappears(monkeypatch):
    book = load_book()
    card = next(
        c
        for c in book.cards
        if c.kind.value == "reference_policy" and c.scope == PolicyScope.保育経過記録
    )
    card.references = [
        r.model_copy(update={"enabled": False}) if r.source == ReferenceSource.period_diary else r
        for r in card.references
    ]
    monkeypatch.setattr(instr, "load_book", lambda: book)
    out = build_author_instruction("BASE", PolicyScope.保育経過記録)(_Ctx({}))
    assert "period_diary" not in out
    assert "prev_child_records" in out


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
