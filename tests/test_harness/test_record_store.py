"""harness/record_store（書類アーカイブ）の単体テスト（LLM/GCP creds 不要・決定論）。

Phase 1（本番運用ブラッシュアップ）：確定書類の永続化・版管理・承認証跡・児童マスタ auto-create・
L2/L3 seed 取得（期間の日誌）・DATABASE_URL 未設定の降格を sqlite で検証する。
スキーマは Base.metadata.create_all（Alembic は実 DB 向けの適用手順・SSOT はモデル側）。
"""

from __future__ import annotations

from datetime import date, datetime

import pytest

from hoiku_agent.config import settings
from hoiku_agent.harness import record_store as rs

_NOW = datetime(2026, 7, 5, 18, 0, 0)


@pytest.fixture()
def db(tmp_path, monkeypatch):
    """sqlite の一時 DB に向けてスキーマを作る（設定は config が唯一の出所＝settings を差し替え）。"""
    url = f"sqlite:///{tmp_path}/archive.db"
    monkeypatch.setattr(settings, "database_url", url)
    rs.reset_engine_cache()
    engine = rs._engine()
    rs.Base.metadata.create_all(engine)
    yield url
    rs.reset_engine_cache()


def _diary_entry(day: str, children: tuple[str, ...] = ("はるとくん", "めいちゃん")) -> dict:
    return {
        "date": day,
        "age_band": "0-2",
        "daily_aim": "戸外で夏の自然に触れる",
        "attendance": [{"child_id": c, "present": True} for c in children],
        "individual_notes": [
            {"child_id": c, "observed_state": f"{c}は水遊びを楽しんだ", "tags": []}
            for c in children
        ],
        "evaluation": {"child_focus": "…", "self_review": "…"},
    }


# ──────────────────────────── 降格（DATABASE_URL 未設定） ────────────────────────────


def test_disabled_when_url_unset(monkeypatch):
    monkeypatch.setattr(settings, "database_url", "")
    rs.reset_engine_cache()
    assert rs.store_status() == "disabled"
    assert rs.save_document("diary", _diary_entry("2026-07-01"), now=_NOW)["status"] == "skipped"
    assert (
        rs.approve_document("diary", _diary_entry("2026-07-01"), actor="x", now=_NOW)["status"]
        == "skipped"
    )
    assert rs.list_diary_entries(date(2026, 7, 1), date(2026, 7, 31)) == []
    assert rs.list_children() == []
    assert rs.list_documents() == []
    assert rs.list_audit_events() == []


# ──────────────────────────── 保存・版・承認 ────────────────────────────


def test_save_creates_document_version_and_children(db):
    r = rs.save_document(
        "diary", _diary_entry("2026-07-01"), "整形テキスト", author_kind="ai", now=_NOW
    )
    assert r["status"] == "saved"
    assert r["version_seq"] == 1
    assert rs.store_status() == "ok"
    # 児童マスタへ auto-create（個別記録・出欠に登場した子）
    names = [c["display_name"] for c in rs.list_children()]
    assert names == sorted(["はるとくん", "めいちゃん"])
    docs = rs.list_documents()
    assert len(docs) == 1
    assert docs[0]["doc_type"] == "diary"
    assert docs[0]["status"] == "finalized"


def test_same_target_upserts_and_stacks_versions(db):
    entry = _diary_entry("2026-07-01")
    r1 = rs.save_document("diary", entry, author_kind="ai", now=_NOW)
    edited = dict(entry, daily_aim="修正後のねらい")
    r2 = rs.save_document("diary", edited, author_kind="caregiver", actor="保育士A", now=_NOW)
    assert r1["document_id"] == r2["document_id"]  # 同一書類（dedupe_key）
    assert r2["version_seq"] == 2
    assert len(rs.list_documents()) == 1
    # 最新版が seed に出る
    entries = rs.list_diary_entries(date(2026, 7, 1), date(2026, 7, 31))
    assert len(entries) == 1
    assert entries[0]["daily_aim"] == "修正後のねらい"


def test_approve_sets_status_and_audit_trail(db):
    entry = _diary_entry("2026-07-01")
    rs.save_document("diary", entry, author_kind="ai", now=_NOW)
    r = rs.approve_document("diary", entry, actor="園長", now=_NOW)
    assert r["status"] == "approved"
    assert rs.list_documents()[0]["status"] == "approved"
    actions = [(e["action"], e["actor"]) for e in rs.list_audit_events()]
    assert ("approve", "園長") in actions
    assert ("finalize", "") in actions


def test_approve_unsaved_document_errors(db):
    r = rs.approve_document("diary", _diary_entry("2026-07-02"), actor="園長", now=_NOW)
    assert r["status"] == "error"


def test_edit_after_approve_keeps_versions(db):
    """承認後の編集も版として積める（証跡が残る・黙って上書きしない）。"""
    entry = _diary_entry("2026-07-01")
    rs.save_document("diary", entry, author_kind="ai", now=_NOW)
    rs.approve_document("diary", entry, actor="園長", now=_NOW)
    r = rs.save_document(
        "diary", dict(entry, daily_aim="追記"), author_kind="caregiver", actor="保育士A", now=_NOW
    )
    assert r["version_seq"] == 2
    assert r["doc_status"] == "approved"


# ──────────────────────────── 月案・児童票・seed クエリ ────────────────────────────


def test_monthly_and_child_record_targets(db):
    monthly = {"month": "2026-07", "child_id": "はるとくん", "age_band": "0-2"}
    record = {"period": "2026-04〜2026-06", "child_id": "はるとくん", "age_band": "0-2"}
    assert rs.save_document("monthly", monthly, author_kind="ai", now=_NOW)["status"] == "saved"
    assert rs.save_document("child_record", record, author_kind="ai", now=_NOW)["status"] == "saved"
    types = {d["doc_type"] for d in rs.list_documents()}
    assert types == {"monthly", "child_record"}
    # 同月・別児は別書類
    monthly2 = dict(monthly, child_id="めいちゃん")
    r = rs.save_document("monthly", monthly2, author_kind="ai", now=_NOW)
    assert r["status"] == "saved"
    assert len([d for d in rs.list_documents() if d["doc_type"] == "monthly"]) == 2


def test_list_diary_entries_filters_by_range(db):
    for day in ("2026-06-30", "2026-07-01", "2026-07-15", "2026-08-01"):
        rs.save_document("diary", _diary_entry(day), author_kind="ai", now=_NOW)
    entries = rs.list_diary_entries(date(2026, 7, 1), date(2026, 7, 31))
    assert [e["date"] for e in entries] == ["2026-07-01", "2026-07-15"]


def test_list_child_record_entries_returns_latest_per_period_for_child(db):
    """児童票の過去期取得（年間マトリクス帳票の埋め込み用）＝その子の最新版だけ・期間順・他児は混ざらない。"""
    q1 = {"period": "2026-04〜2026-06", "child_id": "はるとくん", "overall_note": "1期の所見"}
    rs.save_document("child_record", q1, author_kind="ai", now=_NOW)
    rs.save_document(
        "child_record",
        dict(q1, overall_note="1期の所見（保育士修正）"),
        author_kind="caregiver",
        now=_NOW,
    )
    rs.save_document(
        "child_record",
        {"period": "2026-07〜2026-09", "child_id": "はるとくん", "overall_note": "2期の所見"},
        author_kind="ai",
        now=_NOW,
    )
    rs.save_document(
        "child_record",
        {"period": "2026-04〜2026-06", "child_id": "めいちゃん", "overall_note": "別児の所見"},
        author_kind="ai",
        now=_NOW,
    )
    entries = rs.list_child_record_entries("はるとくん")
    assert [e["period"] for e in entries] == ["2026-04〜2026-06", "2026-07〜2026-09"]
    assert entries[0]["overall_note"] == "1期の所見（保育士修正）"  # 最新版が出る
    # 未登録の子・空文字・降格は空
    assert rs.list_child_record_entries("未登録ちゃん") == []
    assert rs.list_child_record_entries("") == []


def test_missing_target_is_error(db):
    r = rs.save_document("diary", {"age_band": "0-2"}, author_kind="ai", now=_NOW)
    assert r["status"] == "error"
    assert "date" in r["detail"]


def test_invalid_kind_and_author_kind(db):
    assert (
        rs.save_document("weekly", {"date": "2026-07-01"}, author_kind="ai", now=_NOW)["status"]
        == "error"
    )
    assert (
        rs.save_document("diary", _diary_entry("2026-07-01"), author_kind="robot", now=_NOW)[
            "status"
        ]
        == "error"
    )


# ──────────────────────────── users（IAP identity の auto-provision・Phase 3） ────────────────────────────


def test_touch_user_provisions_and_is_idempotent(db):
    r1 = rs.touch_user("sensei@example.com", now=_NOW)
    assert r1 == {
        "status": "ok",
        "email": "sensei@example.com",
        "display_name": "",
        "active": True,
    }
    r2 = rs.touch_user("sensei@example.com", now=_NOW)  # 2回目も同じ行（重複を作らない）
    assert r2["status"] == "ok"
    with rs.Session(rs._engine()) as session:
        emails = [u.email for u in session.scalars(rs.sa.select(rs.User))]
    assert emails == ["sensei@example.com"]


def test_touch_user_degrades(monkeypatch, db):
    assert rs.touch_user("", now=_NOW)["status"] == "skipped"  # 空 email
    monkeypatch.setattr(settings, "database_url", "")
    rs.reset_engine_cache()
    assert rs.touch_user("sensei@example.com", now=_NOW)["status"] == "skipped"  # DB 未設定


# ──────────────────────────── 期間パース（seed の範囲解決・純関数） ────────────────────────────


def test_month_date_range_and_prev_month():
    assert rs.month_date_range("2026-07") == (date(2026, 7, 1), date(2026, 7, 31))
    assert rs.month_date_range("2026-02") == (date(2026, 2, 1), date(2026, 2, 28))
    assert rs.month_date_range("2026-12") == (date(2026, 12, 1), date(2026, 12, 31))
    assert rs.prev_month_of("2026-07") == "2026-06"
    assert rs.prev_month_of("2026-01") == "2025-12"
    with pytest.raises(ValueError):
        rs.prev_month_of("2026-13")


def test_period_date_range_parses_month_span_or_none():
    assert rs.period_date_range("2026-04〜2026-06") == (date(2026, 4, 1), date(2026, 6, 30))
    assert rs.period_date_range("2026-04~2026-06") == (date(2026, 4, 1), date(2026, 6, 30))
    # 期制は園差＝自由記述。月〜月以外は None（黙って誤解釈せず呼び出し側がサンプルへ降格）。
    assert rs.period_date_range("1学期") is None
    assert rs.period_date_range("2026-06〜2026-04") is None  # 逆転も None
