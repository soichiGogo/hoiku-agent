"""harness.notation_store（ひらがな表記DX＝表記ルール辞書＋正規化器）の決定的単体テスト（LLM 非依存）。

設計コンテキスト §5：表記の統一は決定的ロジック（型/表記の保証）なので pytest 必須。正規化は
叙述系フィールドに限定し、仮名（child_id）・タグ・日付には触れないことを型で検証する（§14 の誤変換防止）。
clock は外部注入（固定 datetime）で純粋にテストする。
"""

from __future__ import annotations

from datetime import date, datetime

import pytest

from hoiku_agent.harness import notation_store as ns
from hoiku_agent.schemas.notation import NotationBook, NotationKind, NotationRule

T = datetime(2026, 7, 5, 9, 0, 0)
T2 = datetime(2026, 7, 6, 9, 0, 0)


def _rule(rid: str, pattern: str, replacement: str, *, enabled: bool = True) -> NotationRule:
    return NotationRule(
        id=rid,
        pattern=pattern,
        replacement=replacement,
        kind=NotationKind.ひらがな化,
        source="テスト",
        enabled=enabled,
        created_at=T,
        updated_at=T,
    )


def _seeded() -> NotationBook:
    book = NotationBook()
    book = ns.add_rule(book, _rule("rule-0001", "子供", "子ども"))
    book = ns.add_rule(book, _rule("rule-0002", "友達", "友だち"))
    return book


# ──────────────────────────── 正規化器（純関数） ────────────────────────────


def test_normalize_text_applies_rules_and_counts():
    rules = ns.enabled_rules(_seeded())
    out, changes = ns.normalize_text("子供と子供と友達", rules)
    assert out == "子どもと子どもと友だち"
    by_id = {c["rule_id"]: c for c in changes}
    assert by_id["rule-0001"]["count"] == 2
    assert by_id["rule-0002"]["count"] == 1


def test_normalize_text_disabled_rule_skipped():
    book = NotationBook()
    book = ns.add_rule(book, _rule("rule-0001", "子供", "子ども", enabled=False))
    out, changes = ns.normalize_text("子供", ns.enabled_rules(book))
    assert out == "子供"
    assert changes == []


def test_strip_stray_spaces_between_japanese_only():
    rules: list[NotationRule] = []
    # 日本語文字どうしの半角/全角スペースは除去
    out, changes = ns.normalize_text("仲良く　遊ぶ こと", rules)
    assert out == "仲良く遊ぶこと"
    assert any(c["rule_id"] == ns._SPACE_RULE_ID for c in changes)


def test_strip_keeps_ascii_spaces_and_trims_ends():
    out, _ = ns.normalize_text("  36.5 ℃ の 計測  ", [])
    # ASCII 数字と単位の間の空白は保つ／日本語間は除去／前後は trim
    assert out == "36.5 ℃の計測"


def test_normalize_text_empty_rules_is_noop_text():
    out, changes = ns.normalize_text("子供", [])
    assert out == "子供"
    assert changes == []


# ──────────────────────────── entry 単位の正規化（叙述限定・誤変換防止） ────────────────────────────


def test_normalize_entry_child_record_narrative_only():
    rules = ns.enabled_rules(_seeded())
    data = {
        "period": "2026-04〜2026-06",
        "age_band": "0-2",
        "child_id": "子供テスト仮名",  # 仮名は絶対に変換しない
        "development_notes": [
            {"description": "友達 と 関わる", "tags": ["健やかに伸び伸びと育つ"]},
        ],
        "care_notes": "",
        "family_liaison": "",
        "overall_note": "子供らしい姿",
        "next_aims": "",
    }
    out, changes = ns.normalize_entry_dict(data, "child_record", rules)
    assert out["child_id"] == "子供テスト仮名"  # 仮名は不変
    assert out["development_notes"][0]["description"] == "友だちと関わる"
    assert out["development_notes"][0]["tags"] == ["健やかに伸び伸びと育つ"]  # タグは不変
    assert out["overall_note"] == "子どもらしい姿"
    assert changes  # 変更点が集計される


def test_normalize_entry_diary_nested_paths():
    rules = ns.enabled_rules(_seeded())
    data = {
        "date": "2026-07-05",
        "age_band": "0-2",
        "attendance": [{"child_id": "友達仮名", "present": True, "reason": "子供の発熱"}],
        "individual_notes": [
            {
                "child_id": "子供仮名",
                "observed_state": "友達に興味",
                "tags": [],
                "life_record": {"meal": "", "sleep": "友達と午睡", "toilet": "", "mood_health": ""},
                "individual_aim": "",
            }
        ],
        "evaluation": {"child_focus": "子供の姿", "self_review": ""},
    }
    out, _ = ns.normalize_entry_dict(data, "diary", rules)
    assert out["attendance"][0]["child_id"] == "友達仮名"  # 仮名不変
    assert out["attendance"][0]["reason"] == "子どもの発熱"
    assert out["individual_notes"][0]["child_id"] == "子供仮名"  # 仮名不変
    assert out["individual_notes"][0]["observed_state"] == "友だちに興味"
    assert out["individual_notes"][0]["life_record"]["sleep"] == "友だちと午睡"
    assert out["evaluation"]["child_focus"] == "子どもの姿"


def test_normalize_entry_is_nondestructive():
    rules = ns.enabled_rules(_seeded())
    data = {
        "overall_note": "子供",
        "development_notes": [],
        "period": "p",
        "age_band": "0-2",
        "child_id": "x",
    }
    out, _ = ns.normalize_entry_dict(data, "child_record", rules)
    assert data["overall_note"] == "子供"  # 入力 dict は破壊しない
    assert out["overall_note"] == "子ども"


# ──────────────────────────── 採番・CRUD ────────────────────────────


def test_next_rule_id_empty_and_increment():
    assert ns.next_rule_id(NotationBook()) == "rule-0001"
    assert ns.next_rule_id(_seeded()) == "rule-0003"


def test_add_rule_rejects_empty_dup_id_dup_pattern():
    book = _seeded()
    with pytest.raises(ValueError, match="変換元"):
        ns.add_rule(book, _rule("rule-0009", "  ", "x"))
    with pytest.raises(ValueError, match="id が重複"):
        ns.add_rule(book, _rule("rule-0001", "新", "しん"))
    with pytest.raises(ValueError, match="変換元のルールが既に"):
        ns.add_rule(book, _rule("rule-0009", "子供", "こども"))


def test_update_rule_edits_and_guards():
    book = _seeded()
    book2 = ns.update_rule(book, rule_id="rule-0001", when=T2, replacement="こども", enabled=False)
    r = ns.find_rule(book2, "rule-0001")
    assert r.replacement == "こども" and r.enabled is False and r.updated_at == T2
    # 別ルールの pattern と衝突する編集は弾く
    with pytest.raises(ValueError, match="変換元のルールが既に"):
        ns.update_rule(book, rule_id="rule-0001", when=T2, pattern="友達")
    with pytest.raises(ValueError, match="見つかりません"):
        ns.update_rule(book, rule_id="rule-9999", when=T2, note="x")


def test_remove_rule():
    book = _seeded()
    book2 = ns.remove_rule(book, rule_id="rule-0001")
    assert ns.find_rule(book2, "rule-0001") is None
    assert len(book2.rules) == 1
    with pytest.raises(ValueError, match="見つかりません"):
        ns.remove_rule(book, rule_id="rule-9999")


# ──────────────────────────── IO / store_status / view（ローカル経路） ────────────────────────────


def test_save_load_roundtrip(tmp_path, monkeypatch):
    p = tmp_path / "表記ルール.json"
    monkeypatch.setattr(ns, "_NOTATION_PATH", p)
    ns.save_book(_seeded())
    loaded = ns.load_book()
    assert [r.pattern for r in loaded.rules] == ["子供", "友達"]


def test_load_missing_returns_empty(tmp_path):
    assert ns.load_book(tmp_path / "なし.json").rules == []


def test_load_corrupt_raises(tmp_path):
    p = tmp_path / "壊れ.json"
    p.write_text("{壊れ", encoding="utf-8")
    with pytest.raises(Exception):
        ns.load_book(p)


def test_load_rules_or_empty_degrades_on_corrupt(tmp_path, monkeypatch):
    p = tmp_path / "表記ルール.json"
    p.write_text("{壊れ", encoding="utf-8")
    monkeypatch.setattr(ns, "_NOTATION_PATH", p)
    assert ns.load_rules_or_empty() == []  # 壊れは no-op（確定を落とさない）


def test_store_status_local(tmp_path, monkeypatch):
    p = tmp_path / "表記ルール.json"
    monkeypatch.delenv("K_SERVICE", raising=False)
    assert ns.store_status(p) == "unavailable"
    ns.save_book(_seeded(), p)
    assert ns.store_status(p) == "persistent"
    monkeypatch.setenv("K_SERVICE", "hoiku")
    assert ns.store_status(p) == "ephemeral"


def test_book_view_shape():
    view = ns.book_view(_seeded())
    assert [r["pattern"] for r in view["rules"]] == ["子供", "友達"]
    assert view["rules"][0]["kind"] == "ひらがな化"
    assert view["rules"][0]["enabled"] is True


# ──────────────────────────── DB ストア（DATABASE_URL＝Cloud SQL 統合） ────────────────────────────


def test_db_create_only_then_update(notation_db):
    book, version = ns.load_book_meta()
    assert version == 0  # 行不在＝create-only（ローカルシードは空＝conftest）
    ns.save_book(_seeded(), if_version=version)  # 0＝create-only
    loaded, version2 = ns.load_book_meta()
    assert version2 == 1 and [r.pattern for r in loaded.rules] == ["子供", "友達"]
    ns.save_book(ns.add_rule(loaded, _rule("rule-0003", "出来る", "できる")), if_version=1)
    assert ns.load_book_meta()[1] == 2


def test_db_optimistic_lock_conflict(notation_db):
    ns.save_book(_seeded(), if_version=0)  # version 1
    ns.save_book(_seeded())  # 他所の更新（version 2）
    with pytest.raises(ValueError, match="競合"):
        ns.save_book(_seeded(), if_version=1)


def test_db_store_status_persistent(notation_db):
    assert ns.store_status() == "persistent"


# ──────────────────────────── finalize 経路の正規化（結合・§5） ────────────────────────────


def test_finalize_child_record_normalizes(tmp_path, monkeypatch):
    from hoiku_agent.harness.finalize import finalize_entry

    p = tmp_path / "表記ルール.json"
    monkeypatch.setattr(ns, "_NOTATION_PATH", p)
    ns.save_book(_seeded())
    entry = {
        "period": "2026-04〜2026-06",
        "age_band": "0-2",
        "child_id": "子供仮名",  # 仮名は変換されない
        "development_notes": [{"description": "友達と遊ぶ", "tags": ["健やかに伸び伸びと育つ"]}],
        "overall_note": "子供らしい育ち",
    }
    result = finalize_entry(entry, kind="child_record")
    assert result.entry.child_id == "子供仮名"  # 仮名不変
    assert result.entry.overall_note == "子どもらしい育ち"
    assert result.entry.development_notes[0].description == "友だちと遊ぶ"
    assert "子ども" in result.formatted and "友だち" in result.formatted
    assert result.notation_changes  # 変更点が確定結果に載る


def test_finalize_diary_normalizes_via_doc_date(tmp_path, monkeypatch):
    from hoiku_agent.harness.finalize import finalize_document

    p = tmp_path / "表記ルール.json"
    monkeypatch.setattr(ns, "_NOTATION_PATH", p)
    ns.save_book(_seeded())
    draft = """下書きです。
```json
{"age_band":"0-2","weather":"晴れ","attendance":[{"child_id":"子供仮名","present":true}],
"practice_record":"友達と関わる","individual_notes":[{"child_id":"友達仮名","observed_state":"子供の姿",
"tags":["健やかに伸び伸びと育つ"],"life_record":{"meal":"完了食","sleep":"","toilet":"","mood_health":""}}],
"evaluation":{"child_focus":"子供に焦点","self_review":"ねらい適切"}}
```"""
    result = finalize_document(draft, doc_date=date(2026, 7, 5))
    assert result.entry.attendance[0].child_id == "子供仮名"  # 仮名不変
    assert result.entry.practice_record == "友だちと関わる"
    assert result.entry.individual_notes[0].observed_state == "子どもの姿"
    assert result.entry.evaluation.child_focus == "子どもに焦点"
