"""harness.policy_store（育つ指針＝構造化カードストア）の決定的単体テスト（LLM 非依存）。

設計コンテキスト §8/§16：カードの CRUD・完全重複ガード・履歴・テキスト再生は決定的ロジックなので
pytest 必須。clock は外部注入（固定 datetime）で純粋にテストする。
"""

from __future__ import annotations

from datetime import datetime

import pytest

from hoiku_agent.harness import policy_store as ps
from hoiku_agent.schemas.policy import PolicyBook, PolicyCard, PolicyScope, PolicyStatus

T = datetime(2026, 6, 30, 9, 0, 0)
T2 = datetime(2026, 7, 1, 9, 0, 0)


def _card(cid: str, scope: PolicyScope, body: str, when: datetime = T) -> PolicyCard:
    return PolicyCard(
        id=cid, scope=scope, body=body, source="テスト", created_at=when, updated_at=when
    )


def _seeded() -> PolicyBook:
    book = PolicyBook()
    book = ps.add_card(book, _card("card-0001", PolicyScope.共通, "個人名を書かない"))
    book = ps.add_card(book, _card("card-0002", PolicyScope.月案, "5領域と10の姿に紐づける"))
    return book


# ──────────────────────────── 採番・検索 ────────────────────────────


def test_next_card_id_empty_and_increment():
    assert ps.next_card_id(PolicyBook()) == "card-0001"
    assert ps.next_card_id(_seeded()) == "card-0003"


def test_active_cards_scope_filter():
    book = _seeded()
    assert [c.id for c in ps.active_cards(book)] == ["card-0001", "card-0002"]
    assert [c.id for c in ps.active_cards(book, PolicyScope.月案)] == ["card-0002"]
    assert ps.active_cards(book, PolicyScope.保育日誌) == []


def test_find_exact_duplicate_same_scope_only():
    book = _seeded()
    assert ps.find_exact_duplicate(book, PolicyScope.共通, " 個人名を書かない ").id == "card-0001"
    # 別 scope の同文・部分一致は重複としない（意味的判定は LLM の責務）
    assert ps.find_exact_duplicate(book, PolicyScope.月案, "個人名を書かない") is None
    assert ps.find_exact_duplicate(book, PolicyScope.共通, "個人名") is None


# ──────────────────────────── add / supersede / remove ────────────────────────────


def test_add_card_appends_and_logs_history():
    book = ps.add_card(PolicyBook(), _card("card-0001", PolicyScope.共通, "断定を避ける"))
    assert [c.id for c in book.cards] == ["card-0001"]
    assert len(book.history) == 1 and book.history[0].action.value == "add"
    assert book.history[0].card_id == "card-0001"
    assert book.history[0].timestamp == T


def test_add_card_rejects_empty_duplicate_id_and_exact_dup():
    book = _seeded()
    with pytest.raises(ValueError):
        ps.add_card(book, _card("card-0003", PolicyScope.共通, "   "))  # 空 body
    with pytest.raises(ValueError):
        ps.add_card(book, _card("card-0001", PolicyScope.保育日誌, "別文"))  # id 重複
    with pytest.raises(ValueError):
        ps.add_card(book, _card("card-0003", PolicyScope.共通, "個人名を書かない"))  # 完全重複


def test_supersede_marks_old_and_links_new():
    book = _seeded()
    new = _card("card-0003", PolicyScope.共通, "個人名は仮名・属性で表す", when=T2)
    out = ps.supersede_card(book, old_id="card-0001", new_card=new)

    old = ps.find_card(out, "card-0001")
    assert old.status == PolicyStatus.superseded and old.superseded_by == "card-0003"
    new_c = ps.find_card(out, "card-0003")
    assert new_c.status == PolicyStatus.active and new_c.supersedes == "card-0001"
    assert [c.id for c in ps.active_cards(out, PolicyScope.共通)] == ["card-0003"]
    assert out.history[-1].action.value == "supersede"
    assert out.history[-1].superseded_id == "card-0001"


def test_supersede_missing_or_inactive_raises():
    book = _seeded()
    with pytest.raises(ValueError):
        ps.supersede_card(
            book, old_id="card-9999", new_card=_card("card-0003", PolicyScope.共通, "x")
        )


def test_remove_card_soft_deletes():
    book = _seeded()
    out = ps.remove_card(book, card_id="card-0002", summary="取り下げ", when=T2)
    assert ps.find_card(out, "card-0002").status == PolicyStatus.retired
    assert ps.active_cards(out, PolicyScope.月案) == []
    assert out.history[-1].action.value == "remove"


# ──────────────────────────── render_to_text ────────────────────────────


def test_render_to_text_full_sections_active_only():
    book = _seeded()
    book = ps.supersede_card(
        book,
        old_id="card-0001",
        new_card=_card("card-0003", PolicyScope.共通, "仮名で表す", when=T2),
    )
    text = ps.render_to_text(book)
    assert "## 共通ルール（園・書類横断）" in text
    assert "### 保育日誌" in text and "- （未登録）" in text  # 空 scope
    assert "### 月案 / 週案 / 日案" in text
    assert "- 仮名で表す" in text  # active 新カード
    # superseded カードは active 箇条書きには出さない（変更履歴の要約には旧文が残りうる）。
    common_section = text.split("## 共通ルール")[1].split("## 書類別の勘所")[0]
    assert "個人名を書かない" not in common_section
    assert "## 変更履歴" in text


def test_render_to_text_scope_only():
    text = ps.render_to_text(_seeded(), PolicyScope.月案)
    assert text.startswith("### 月案 / 週案 / 日案")
    assert "- 5領域と10の姿に紐づける" in text
    assert "## 共通ルール" not in text


def test_render_empty_book():
    text = ps.render_to_text(PolicyBook())
    assert "- （未登録）" in text and "- （更新なし）" in text


# ──────────────────────────── IO / store_status / view ────────────────────────────


def test_save_load_roundtrip(tmp_path, monkeypatch):
    p = tmp_path / "文書作成指針.json"
    monkeypatch.setattr(ps, "_POLICY_PATH", p)
    book = _seeded()
    ps.save_book(book)  # 既定 path = monkeypatch 後の _POLICY_PATH
    loaded = ps.load_book()
    assert [c.id for c in loaded.cards] == ["card-0001", "card-0002"]
    assert loaded.cards[0].created_at == T


def test_load_missing_returns_empty(tmp_path):
    assert ps.load_book(tmp_path / "なし.json").cards == []


def test_load_corrupt_raises(tmp_path):
    p = tmp_path / "壊れ.json"
    p.write_text("{ not json", encoding="utf-8")
    with pytest.raises(ValueError):
        ps.load_book(p)


def test_store_status(tmp_path, monkeypatch):
    p = tmp_path / "文書作成指針.json"
    monkeypatch.delenv("K_SERVICE", raising=False)
    assert ps.store_status(p) == "unavailable"
    ps.save_book(_seeded(), p)
    assert ps.store_status(p) == "persistent"
    monkeypatch.setenv("K_SERVICE", "hoiku")
    assert ps.store_status(p) == "ephemeral"


def test_book_view_shapes():
    view = ps.book_view(_seeded())
    assert {"cards", "history"} <= view.keys()
    card = view["cards"][0]
    assert card["doc_type"] == "common" and card["doc_label"] == "共通"
    assert {"at", "by", "summary", "card_id"} <= view["history"][0].keys()
    # history は newest first
    assert view["history"][0]["card_id"] == "card-0002"
