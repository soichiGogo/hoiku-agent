"""harness.template_store の単体テスト（LLM 非依存）。

様式テンプレート（本文レイアウトのデータ）ストアの IO・検索・降格・DB 楽観ロックを検証する
（notation_store のストアテストと対称）。seed（`knowledge/様式テンプレート.json`）の完全性
（4種別が揃い draft.py が期待する doc_type を引ける）も担保する。
"""

from __future__ import annotations

import pytest

from hoiku_agent.harness import template_store as ts
from hoiku_agent.schemas.template import DocTemplate, Section, SectionKind, TemplateBook


def _book() -> TemplateBook:
    return TemplateBook(
        templates=[
            DocTemplate(
                doc_type="diary",
                sections=[
                    Section(key="daily_aim", label="本日のねらい", kind=SectionKind.text_block)
                ],
            )
        ]
    )


# ──────────────────────────── seed の完全性（同梱シード） ────────────────────────────


def test_seed_has_all_four_doc_types():
    """同梱シードに 4 種別が揃い、draft.py が引く doc_type をすべて解決できる。"""
    book = ts.load_book()  # 明示 path 無し＝DATABASE_URL 空（conftest）→ リポ同梱シード
    doc_types = {t.doc_type for t in book.templates}
    assert doc_types == {"diary", "monthly", "child_record", "nursery_record"}


def test_seed_sections_are_valid_kinds():
    """seed の各セクションが閉じた種別語彙に収まる（未知種別で描画時に落ちない）。"""
    for tmpl in ts.load_book().templates:
        assert tmpl.sections, f"{tmpl.doc_type} のセクションが空"
        for s in tmpl.sections:
            assert isinstance(s.kind, SectionKind)


def test_load_template_returns_doc_type():
    tmpl = ts.load_template("monthly")
    assert tmpl.doc_type == "monthly"
    assert any(s.kind is SectionKind.tagged_list for s in tmpl.sections)  # 教育＝tagged_list


def test_load_template_missing_raises():
    with pytest.raises(ValueError, match="doc_type"):
        ts.load_template("weekly")


def test_book_view_shape():
    """/api/doc-template 契約＝doc_type→[{key,label,kind,item_field}]（編集フォームが順序/ラベルに使う）。"""
    view = ts.book_view(ts.load_book())
    assert set(view["templates"]) == {"diary", "monthly", "child_record", "nursery_record"}
    diary = view["templates"]["diary"]
    assert diary[0]["key"] == "daily_aim" and "label" in diary[0] and "kind" in diary[0]
    # tagged_list は item_field を持つ（月案の教育）。
    edu = next(s for s in view["templates"]["monthly"] if s["kind"] == "tagged_list")
    assert edu["item_field"] == "aim"


# ──────────────────────────── IO / store_status（ローカル経路） ────────────────────────────


def test_save_load_roundtrip(tmp_path):
    p = tmp_path / "様式テンプレート.json"
    ts.save_book(_book(), p)
    loaded = ts.load_book(p)
    assert [t.doc_type for t in loaded.templates] == ["diary"]


def test_load_missing_returns_empty(tmp_path):
    assert ts.load_book(tmp_path / "なし.json").templates == []


def test_load_corrupt_raises(tmp_path):
    p = tmp_path / "壊れ.json"
    p.write_text("{壊れ", encoding="utf-8")
    with pytest.raises(Exception):
        ts.load_book(p)


def test_store_status_local(tmp_path, monkeypatch):
    p = tmp_path / "様式テンプレート.json"
    monkeypatch.delenv("K_SERVICE", raising=False)
    assert ts.store_status(p) == "unavailable"
    ts.save_book(_book(), p)
    assert ts.store_status(p) == "persistent"
    monkeypatch.setenv("K_SERVICE", "hoiku")
    assert ts.store_status(p) == "ephemeral"


# ──────────────────────────── DB ストア（DATABASE_URL＝Cloud SQL 統合） ────────────────────────────


def test_db_create_only_then_update(template_db):
    book, version = ts.load_book_meta()
    assert version == 0  # 行不在＝create-only（ローカルシードは空＝conftest）
    ts.save_book(_book(), if_version=version)  # 0＝create-only
    loaded, version2 = ts.load_book_meta()
    assert version2 == 1 and [t.doc_type for t in loaded.templates] == ["diary"]
    ts.save_book(loaded, if_version=1)
    assert ts.load_book_meta()[1] == 2


def test_db_optimistic_lock_conflict(template_db):
    ts.save_book(_book(), if_version=0)  # version 1
    ts.save_book(_book())  # 他所の更新（version 2）
    with pytest.raises(ValueError, match="競合"):
        ts.save_book(_book(), if_version=1)


def test_db_store_status_persistent(template_db):
    assert ts.store_status() == "persistent"
