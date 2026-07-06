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


# ──────────────────────────── 単一書類の全文取得（書類を見る＝アーカイブ閲覧） ────────────────────────────


def test_get_document_returns_current_version_full(db):
    """get_document は現行版の本文 entry＋整形テキスト＋確定/編集の区別を返す（閲覧の主眼）。"""
    entry = _diary_entry("2026-07-01")
    r = rs.save_document("diary", entry, "整形テキスト本文", author_kind="ai", now=_NOW)
    got = rs.get_document(r["document_id"])
    assert got is not None
    assert got["doc_type"] == "diary"
    assert got["rendered_text"] == "整形テキスト本文"
    assert got["author_kind"] == "ai"
    assert got["version_seq"] == 1
    assert got["entry"]["date"] == "2026-07-01"
    # 編集で版が積まれたら現行版（最新）が返る（担当者・整形テキストも最新に追従）。
    rs.save_document(
        "diary",
        dict(entry, daily_aim="修正後"),
        "整形v2",
        author_kind="caregiver",
        actor="保育士A",
        now=_NOW,
    )
    got2 = rs.get_document(r["document_id"])
    assert got2["version_seq"] == 2
    assert got2["author_kind"] == "caregiver"
    assert got2["created_by"] == "保育士A"
    assert got2["rendered_text"] == "整形v2"
    assert got2["entry"]["daily_aim"] == "修正後"


def test_get_document_missing_or_invalid_is_none(db):
    import uuid as _uuid

    assert rs.get_document(str(_uuid.uuid4())) is None  # 不在
    assert rs.get_document("not-a-uuid") is None  # 不正 id（例外にしない）


def test_get_document_degrades_when_url_unset(monkeypatch):
    monkeypatch.setattr(settings, "database_url", "")
    rs.reset_engine_cache()
    assert rs.get_document("any-id") is None


# ──────────────────────────── 月案・保育経過記録・seed クエリ ────────────────────────────


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


def test_class_monthly_is_class_level_and_auto_creates_goal_children(db):
    """クラス月案（class_monthly）はクラス単位（主対象児なし・月が対象期間キー）で保存でき、
    個人目標の登場児が児童マスタへ auto-create される（§18）。"""
    plan = {
        "month": "2026-07",
        "age_band": "0-2",
        "class_name": "ひよこ組",
        "individual_goals": [
            {"child_id": "はるとくん", "child_state": "s", "aim_support": "a"},
            {"child_id": "めいちゃん", "child_state": "s", "aim_support": "a"},
        ],
    }
    assert rs.save_document("class_monthly", plan, author_kind="ai", now=_NOW)["status"] == "saved"
    docs = [d for d in rs.list_documents() if d["doc_type"] == "class_monthly"]
    assert len(docs) == 1
    assert docs[0]["child"] in (None, "")  # クラス単位＝主対象児は持たない
    # 個人目標の登場児が児童マスタへ登録される（下流の候補ソースになる）。
    names = {c["display_name"] for c in rs.list_children()}
    assert {"はるとくん", "めいちゃん"} <= names
    # 同月・同クラス（年齢帯）は同一書類として版が積まれる（クラス月案は月＝同一性キー）。
    r2 = rs.save_document("class_monthly", plan, author_kind="caregiver", now=_NOW)
    assert r2["status"] == "saved"
    assert len([d for d in rs.list_documents() if d["doc_type"] == "class_monthly"]) == 1
    # month 欠落は fail-loud（同一性キーを黙って空にしない）。
    bad = rs.save_document("class_monthly", {"age_band": "0-2"}, now=_NOW)
    assert bad["status"] == "error"


def test_nursery_record_target_is_fiscal_year(db):
    """保育要録（L4）は fiscal_year を対象期間キーにして保存でき、同年度・別児は別書類（§19）。"""
    rec = {"fiscal_year": "2026", "child_id": "はるとくん", "age_band": "3-5"}
    assert rs.save_document("nursery_record", rec, author_kind="ai", now=_NOW)["status"] == "saved"
    types = {d["doc_type"] for d in rs.list_documents()}
    assert "nursery_record" in types
    # 同年度・別児は別書類
    rec2 = dict(rec, child_id="めいちゃん")
    assert rs.save_document("nursery_record", rec2, author_kind="ai", now=_NOW)["status"] == "saved"
    assert len([d for d in rs.list_documents() if d["doc_type"] == "nursery_record"]) == 2
    # fiscal_year 欠落は fail-loud（同一性キーを黙って空にしない）
    bad = rs.save_document("nursery_record", {"child_id": "はるとくん"}, now=_NOW)
    assert bad["status"] == "error"


def test_list_diary_entries_filters_by_range(db):
    for day in ("2026-06-30", "2026-07-01", "2026-07-15", "2026-08-01"):
        rs.save_document("diary", _diary_entry(day), author_kind="ai", now=_NOW)
    entries = rs.list_diary_entries(date(2026, 7, 1), date(2026, 7, 31))
    assert [e["date"] for e in entries] == ["2026-07-01", "2026-07-15"]


def test_list_child_record_entries_returns_latest_per_period_for_child(db):
    """保育経過記録の過去期取得（年間マトリクス帳票の埋め込み用）＝その子の最新版だけ・期間順・他児は混ざらない。"""
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


def test_imported_author_kind_records_import_audit(db):
    """アップロード取込（author_kind="imported"）は保存され、監査アクションが "import" になる。

    AI 確定（finalize）・保育士編集（edit）と混ざらない第三の来歴＝「修正差分の一次データ」を汚さない。
    """
    entry = _diary_entry("2026-07-01")
    r = rs.save_document(
        "diary", entry, "整形テキスト", author_kind="imported", actor="保育士A", now=_NOW
    )
    assert r["status"] == "saved"
    # 版の来歴は imported として残る（get_document は現行版の author_kind を返す）。
    got = rs.get_document(r["document_id"])
    assert got["author_kind"] == "imported"
    # 監査アクションは import（finalize/edit ではない）。
    actions = [
        (e["action"], e["actor"]) for e in rs.list_audit_events(document_id=r["document_id"])
    ]
    assert ("import", "保育士A") in actions
    assert not any(a in ("finalize", "edit") for a, _ in actions)


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


def test_set_user_display_name_provisions_and_updates(db):
    # 未登録 email でも auto-provision して表示名を設定できる（touch_user 前でも作る）。
    r1 = rs.set_user_display_name("sensei@example.com", "そうた先生", now=_NOW)
    assert r1["status"] == "ok"
    assert r1["email"] == "sensei@example.com"
    assert r1["display_name"] == "そうた先生"
    # 以後 touch_user が設定済みの表示名を返す＝actor 証跡・/api/config に乗る。
    assert rs.touch_user("sensei@example.com", now=_NOW)["display_name"] == "そうた先生"
    # 空白のみはクリアを許す（表示名を消すと actor は email に戻る）。重複行は作らない。
    r2 = rs.set_user_display_name("sensei@example.com", "  ", now=_NOW)
    assert r2["display_name"] == ""
    with rs.Session(rs._engine()) as session:
        emails = [u.email for u in session.scalars(rs.sa.select(rs.User))]
    assert emails == ["sensei@example.com"]
    # 列上限（100）へ clamp。
    long = rs.set_user_display_name("long@example.com", "あ" * 150, now=_NOW)
    assert len(long["display_name"]) == 100


def test_set_user_display_name_degrades(monkeypatch, db):
    assert rs.set_user_display_name("", "名前", now=_NOW)["status"] == "skipped"  # 空 email
    monkeypatch.setattr(settings, "database_url", "")
    rs.reset_engine_cache()
    assert (
        rs.set_user_display_name("s@example.com", "名前", now=_NOW)["status"] == "skipped"
    )  # DB 未設定


def test_upsert_child_creates_fills_birthdate_and_is_idempotent(db):
    r1 = rs.upsert_child("つむぎちゃん", birthdate=date(2021, 11, 18), now=_NOW)
    assert r1["status"] == "created"
    assert r1["display_name"] == "つむぎちゃん"
    assert r1["birthdate"] == "2021-11-18"
    # 2回目は既存＝重複を作らない（表示名 upsert）。
    r2 = rs.upsert_child("つむぎちゃん", birthdate=date(2000, 1, 1), now=_NOW)
    assert r2["status"] == "exists"
    assert r2["birthdate"] == "2021-11-18"  # 既存の誕生日は上書きしない
    names = [c["display_name"] for c in rs.list_children()]
    assert names.count("つむぎちゃん") == 1


def test_upsert_child_fills_missing_birthdate_on_existing_row(db):
    # 先に誕生日なしで作られた行（例：書類の auto-create）に後から補完できる。
    assert rs.upsert_child("れんくん", now=_NOW)["birthdate"] is None
    r = rs.upsert_child("れんくん", birthdate=date(2021, 9, 3), now=_NOW)
    assert r["status"] == "exists"
    assert r["birthdate"] == "2021-09-03"


def test_upsert_child_degrades(monkeypatch, db):
    assert rs.upsert_child("", now=_NOW)["status"] == "skipped"  # 空名
    monkeypatch.setattr(settings, "database_url", "")
    rs.reset_engine_cache()
    assert rs.upsert_child("つむぎちゃん", now=_NOW)["status"] == "skipped"  # DB 未設定


def test_honorific_and_name_helpers():
    # 性別→敬称は固定（男→くん / 女→ちゃん）。呼び名＋敬称＝表示名（child_id 同定キー）。
    assert rs.honorific_for("male") == "くん"
    assert rs.honorific_for("female") == "ちゃん"
    assert rs.honorific_for("") == "" and rs.honorific_for(None) == ""
    assert rs.compose_display_name("はると", "male") == "はるとくん"
    assert rs.compose_display_name("ゆい", "female") == "ゆいちゃん"
    assert rs.compose_display_name("そら", "") == "そら"  # 性別不明は敬称なし
    # 氏名欄＝姓＋名（全角空白区切り・空要素は詰める）。
    assert rs.official_full_name("佐藤", "はると") == "佐藤　はると"
    assert rs.official_full_name("", "はると") == "はると"
    assert rs.official_full_name("", "") == ""


def test_upsert_child_stores_real_name_and_gender(db):
    r = rs.upsert_child(
        "はるとくん", family_name="佐藤", given_name="はると", gender="male", now=_NOW
    )
    assert r["status"] == "created"
    assert r["family_name"] == "佐藤" and r["given_name"] == "はると" and r["gender"] == "male"
    assert r["official_name"] == "佐藤　はると"  # 氏名欄用の本名（姓＋名）
    # get_child でも本名/性別を引ける（帳票PDF の氏名欄解決に使う）。
    got = rs.get_child("はるとくん")
    assert got["official_name"] == "佐藤　はると" and got["gender"] == "male"
    # list_children にも新フィールドが乗る（UI の選択肢＋年齢帯判定）。
    row = next(c for c in rs.list_children() if c["display_name"] == "はるとくん")
    assert row["given_name"] == "はると" and row["official_name"] == "佐藤　はると"


def test_upsert_child_fills_missing_name_fields_only(db):
    # auto-create（書類登場）で display_name だけの行に、後から本名/性別を補完できる。
    rs.upsert_child("ゆいちゃん", now=_NOW)
    r = rs.upsert_child(
        "ゆいちゃん", family_name="鈴木", given_name="ゆい", gender="female", now=_NOW
    )
    assert r["status"] == "exists" and r["official_name"] == "鈴木　ゆい"
    # 既存の非空フィールドは上書きしない（保育士が整えた値を壊さない＝birthdate と同じ流儀）。
    r2 = rs.upsert_child("ゆいちゃん", family_name="別姓", now=_NOW)
    assert r2["family_name"] == "鈴木"


def test_get_child_absent_and_degraded(monkeypatch, db):
    assert rs.get_child("いないくん") is None  # 不在
    monkeypatch.setattr(settings, "database_url", "")
    rs.reset_engine_cache()
    assert rs.get_child("はるとくん") is None  # 未接続降格


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
