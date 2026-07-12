"""harness/record_store（書類アーカイブ）の単体テスト（LLM/GCP creds 不要・決定論）。

Phase 1（本番運用ブラッシュアップ）：確定書類の永続化・版管理・承認証跡・児童マスタ auto-create・
L2/L3 seed 取得（期間の日誌）・DATABASE_URL 未設定の降格を sqlite で検証する。
スキーマは Base.metadata.create_all（Alembic は実 DB 向けの適用手順・SSOT はモデル側）。
"""

from __future__ import annotations

from datetime import date, datetime
import uuid

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


def test_approval_candidate_and_memory_sync_are_version_scoped(db):
    """同期済み印は承認した版だけに付き、編集で新しい版が積まれると未同期へ戻る。"""
    entry = _diary_entry("2026-07-11")
    saved = rs.save_document("diary", entry, author_kind="caregiver", now=_NOW)
    candidate = rs.get_approval_candidate("diary", entry, expected_version_seq=saved["version_seq"])
    assert candidate["status"] == "ready" and candidate["memory_synced"] is False
    approved = rs.approve_document(
        "diary",
        entry,
        actor="園長",
        now=_NOW,
        expected_version_seq=saved["version_seq"],
        memory_synced_version_id=candidate["version_id"],
        memory_status="synced",
    )
    assert approved["memory_status"] == "synced"
    assert rs.list_documents()[0]["memory_synced"] is True

    rs.save_document("diary", entry, author_kind="caregiver", now=_NOW)
    doc = rs.list_documents()[0]
    assert doc["status"] == "finalized" and doc["memory_synced"] is False


def test_approve_unsaved_document_errors(db):
    r = rs.approve_document("diary", _diary_entry("2026-07-02"), actor="園長", now=_NOW)
    assert r["status"] == "error"


def test_edit_after_approve_keeps_versions_and_revokes_approval(db):
    """承認後の編集も版として積める（証跡が残る）。ただし承認は失効し finalized へ戻る（偽の緑を出さない）。

    書類管理タブでの編集（caregiver・decision A）は編集→再承認の流れに乗る＝編集後の現行内容を
    「承認済み」と偽らない。旧内容への承認証跡（audit）は残る。
    """
    entry = _diary_entry("2026-07-01")
    rs.save_document("diary", entry, author_kind="ai", now=_NOW)
    rs.approve_document("diary", entry, actor="園長", now=_NOW)
    r = rs.save_document(
        "diary", dict(entry, daily_aim="追記"), author_kind="caregiver", actor="保育士A", now=_NOW
    )
    assert r["version_seq"] == 2
    assert r["doc_status"] == "finalized"  # 承認失効＝現行版は未承認へ（再承認が要る）
    assert rs.list_documents()[0]["status"] == "finalized"
    # 旧内容への承認証跡は audit に残る（黙って消さない）。
    actions = [e["action"] for e in rs.list_audit_events()]
    assert "approve" in actions and actions.count("edit") == 1


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


def test_child_record_save_normalizes_period_and_rejects_non_quarter(db):
    record = {"period": "2026-04～2026-06", "child_id": "はるとくん", "age_band": "0-2"}
    saved = rs.save_document("child_record", record, author_kind="ai", now=_NOW)
    assert saved["status"] == "saved"
    detail = rs.get_document(saved["document_id"])
    assert detail is not None and detail["entry"]["period"] == "2026-04〜2026-06"

    invalid = rs.save_document(
        "child_record",
        {**record, "period": "2026-04〜2026-07"},
        author_kind="ai",
        now=_NOW,
    )
    assert invalid["status"] == "error"
    assert "年度4期の3か月単位" in invalid["detail"]


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


def test_list_diary_meta_flags_evaluation_completeness(db):
    """日誌メタ（id/日付/状態/評価充足）を日付順に返す＝クラス月案の未記入検出用。

    評価・反省は2視点とも記入で complete。片方でも空なら未記入（validate_fields と同じ判定）。
    """
    # 6/10=両視点あり（complete）、6/11=(b)空（未記入）、6/20=(a)空（未記入）
    e_full = _diary_entry("2026-06-10")
    e_no_b = dict(_diary_entry("2026-06-11"), evaluation={"child_focus": "あり", "self_review": ""})
    e_no_a = dict(_diary_entry("2026-06-20"), evaluation={"child_focus": "", "self_review": "あり"})
    for e in (e_full, e_no_b, e_no_a):
        rs.save_document("diary", e, author_kind="ai", now=_NOW)

    meta = rs.list_diary_meta(date(2026, 6, 1), date(2026, 6, 30))
    assert [m["date"] for m in meta] == ["2026-06-10", "2026-06-11", "2026-06-20"]  # 日付順
    by_date = {m["date"]: m for m in meta}
    assert by_date["2026-06-10"]["evaluation_complete"] is True
    assert by_date["2026-06-11"]["evaluation_complete"] is False  # (b) 空＝未記入
    assert by_date["2026-06-20"]["evaluation_complete"] is False  # (a) 空＝未記入
    # id はフロントが「その日誌へ飛んで編集」する導線に使う＝存在すること。
    assert all(m["id"] for m in meta)
    # age_band＝クラス月案がクラス（年齢帯）の日誌だけに絞るために返す。
    assert by_date["2026-06-10"]["age_band"] == "0-2"


def test_list_diary_meta_empty_when_disabled(monkeypatch):
    """DATABASE_URL 未設定は降格＝空（読取は落とさない）。"""
    monkeypatch.setattr(settings, "database_url", "")
    rs.reset_engine_cache()
    assert rs.list_diary_meta(date(2026, 6, 1), date(2026, 6, 30)) == []


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
    # exclude_period＝作成対象の期を「前回まで」に混ぜない（保育経過記録の自己履歴 seed 用）。
    past = rs.list_child_record_entries("はるとくん", exclude_period="2026-07〜2026-09")
    assert [e["period"] for e in past] == ["2026-04〜2026-06"]
    # 未登録の子・空文字・降格は空
    assert rs.list_child_record_entries("未登録ちゃん") == []
    assert rs.list_child_record_entries("") == []


def test_covered_until_takes_max_end_and_skips_unparseable():
    """covered_until＝経過記録に反映済みの最終日（期間終了日の最大・解釈不能は寄与しない＝安全側）。"""
    assert rs.covered_until([]) is None
    assert rs.covered_until(["でたらめ", ""]) is None  # 全部解釈不能＝全日誌が未反映
    assert rs.covered_until(["2026-04〜2026-06"]) == date(2026, 6, 30)
    # 順不同でも最大端。年度跨ぎ（2026-12〜2027-02）も日付比較で自然に扱う。
    assert rs.covered_until(["2026-07〜2026-09", "2026-04〜2026-06"]) == date(2026, 9, 30)
    assert rs.covered_until(["2026-12〜2027-02", "自由記述の期"]) == date(2027, 2, 28)


def test_age_band_for_birthdate_uses_the_fiscal_year_start():
    """クラスの年齢帯は4月1日時点の在籍児から導出し、誕生日境界を推測しない。"""
    as_of = date(2026, 4, 1)
    assert rs.age_band_for_birthdate(date(2023, 4, 1), as_of) == "3-5"
    assert rs.age_band_for_birthdate(date(2023, 4, 2), as_of) == "0-2"
    assert rs.age_band_for_birthdate(None, as_of) is None


def test_roster_age_band_treats_midyear_birth_as_infant():
    """名簿分類は年度初日より後の出生（途中入園の0歳児）を "0-2" に入れる（None で落とさない）。"""
    fs = date(2026, 4, 1)
    assert rs.roster_age_band(date(2026, 5, 10), fs) == "0-2"
    assert rs.roster_age_band(date(2023, 4, 1), fs) == "3-5"
    assert rs.roster_age_band(None, fs) is None


def test_list_class_child_record_entries_prefers_roster(db):
    """クラス児童の保育経過記録＝名簿（Class）優先で全期（年度跨ぎ・別帯で書かれた過去記録も）を引く。"""
    cid = rs.upsert_class("ひよこ組", "2026", now=_NOW)["id"]
    rs.upsert_child(
        "はるとくん", given_name="はると", gender="male", birthdate=date(2023, 4, 2), now=_NOW
    )
    rs.assign_child_to_class("はるとくん", cid, now=_NOW)
    # はるとくんの記録2件（うち1件は前年度・別の年齢帯で書かれた記録＝名簿経由なら拾える）
    rs.save_document(
        "child_record",
        {"period": "2025-10〜2025-12", "child_id": "はるとくん", "age_band": "3-5"},
        author_kind="ai",
        now=_NOW,
    )
    rs.save_document(
        "child_record",
        {"period": "2026-04〜2026-06", "child_id": "はるとくん", "age_band": "0-2"},
        author_kind="ai",
        now=_NOW,
    )
    # クラス外の子の記録（同じ年齢帯でも名簿優先なら混ざらない）
    rs.save_document(
        "child_record",
        {"period": "2026-04〜2026-06", "child_id": "よそのこちゃん", "age_band": "0-2"},
        author_kind="ai",
        now=_NOW,
    )
    entries = rs.list_class_child_record_entries("0-2")
    assert [(e["child_id"], e["period"]) for e in entries] == [
        ("はるとくん", "2025-10〜2025-12"),
        ("はるとくん", "2026-04〜2026-06"),
    ]


def test_list_class_child_record_entries_falls_back_to_age_band(db):
    """名簿未整備（クラス未定義）は entry の age_band 一致で降格フィルタ（v0＝年齢帯≒クラス）。"""
    rs.save_document(
        "child_record",
        {"period": "2026-04〜2026-06", "child_id": "はるとくん", "age_band": "0-2"},
        author_kind="ai",
        now=_NOW,
    )
    rs.save_document(
        "child_record",
        {"period": "2026-04〜2026-06", "child_id": "さくらちゃん", "age_band": "3-5"},
        author_kind="ai",
        now=_NOW,
    )
    entries = rs.list_class_child_record_entries("0-2")
    assert [e["child_id"] for e in entries] == ["はるとくん"]


def test_list_class_monthly_entries_orders_and_bounds_by_month(db):
    """過去クラス月案＝当該年齢帯・対象月より前・月順（年度跨ぎ含む全期）。最新版が出る。"""
    for month in ("2026-05", "2026-04", "2026-07"):
        rs.save_document(
            "class_monthly",
            {"month": month, "age_band": "0-2", "monthly_goal": f"{month} の目標"},
            author_kind="ai",
            now=_NOW,
        )
    rs.save_document(  # 別の年齢帯は混ざらない
        "class_monthly",
        {"month": "2026-05", "age_band": "3-5", "monthly_goal": "別クラス"},
        author_kind="ai",
        now=_NOW,
    )
    rs.save_document(  # 版が積まれたら最新版
        "class_monthly",
        {"month": "2026-04", "age_band": "0-2", "monthly_goal": "2026-04 の目標（修正）"},
        author_kind="caregiver",
        now=_NOW,
    )
    plans = rs.list_class_monthly_entries("0-2", before_month="2026-07")
    assert [p["month"] for p in plans] == ["2026-04", "2026-05"]
    assert plans[0]["monthly_goal"] == "2026-04 の目標（修正）"
    # before_month なしは全部（月順）。
    assert [p["month"] for p in rs.list_class_monthly_entries("0-2")] == [
        "2026-04",
        "2026-05",
        "2026-07",
    ]


def test_class_monthly_seed_inputs_composes_uncovered_diaries_records_and_plans(db):
    """クラス月案 seed 合成＝①クラス児童の全経過記録 ②過去クラス月案 ③経過記録に未反映の期間の日誌。"""
    # 経過記録：4〜6月をカバー（境界＝6/30）
    rs.save_document(
        "child_record",
        {"period": "2026-04〜2026-06", "child_id": "はるとくん", "age_band": "0-2"},
        author_kind="ai",
        now=_NOW,
    )
    # 日誌：6月（反映済み）と7月（未反映）
    rs.save_document("diary", _diary_entry("2026-06-20"), author_kind="caregiver", now=_NOW)
    rs.save_document("diary", _diary_entry("2026-07-10"), author_kind="caregiver", now=_NOW)
    # 過去クラス月案：7月分（対象月8月より前）
    rs.save_document(
        "class_monthly",
        {"month": "2026-07", "age_band": "0-2", "monthly_goal": "7月の目標"},
        author_kind="ai",
        now=_NOW,
    )
    seed = rs.class_monthly_seed_inputs("0-2", "2026-08")
    # 6/20 は はるとくん には反映済みだが、記録の無い めいちゃん には未反映 → 児童別境界で保持する
    # （クラス一律 max 境界だと 6/20 が丸ごと落ち めいちゃん の姿が消えていた欠陥の是正）。
    assert [e["date"] for e in seed["class_diary_entries"]] == ["2026-06-20", "2026-07-10"]
    assert [r["period"] for r in seed["class_record_entries"]] == ["2026-04〜2026-06"]
    assert [p["month"] for p in seed["past_class_plans"]] == ["2026-07"]


def test_class_monthly_seed_keeps_lagging_child_diary_before_others_boundary(db):
    """記録が遅れている児（途中入園児等）の日誌が、記録の進んだ児の境界より前でも seed に残る（児童別境界）。"""
    # A は 4〜6月の記録あり（境界 6/30）／B は記録なし（途中入園）。
    rs.save_document(
        "child_record",
        {"period": "2026-04〜2026-06", "child_id": "Aちゃん", "age_band": "0-2"},
        author_kind="ai",
        now=_NOW,
    )
    # 6/15 の日誌に B だけが登場（A の境界より前だが B には未反映）。
    rs.save_document(
        "diary",
        _diary_entry("2026-06-15", children=("Bちゃん",)),
        author_kind="caregiver",
        now=_NOW,
    )
    seed = rs.class_monthly_seed_inputs("0-2", "2026-08")
    # クラス一律 max 境界（6/30）なら 6/15 は落ちるが、B は未反映なので保持されるのが正しい。
    assert [e["date"] for e in seed["class_diary_entries"]] == ["2026-06-15"]


def test_covered_until_by_child_is_per_child(db):
    """covered_until_by_child は児童別の反映済み最終日を返し、記録の無い児は現れない（境界なし＝全未反映）。"""
    records = [
        {"child_id": "Aちゃん", "period": "2026-04〜2026-06"},
        {"child_id": "Aちゃん", "period": "2026-07〜2026-09"},  # 最大を採る
        {"child_id": "Cちゃん", "period": "2026-04〜2026-06"},
        {"child_id": "Dちゃん", "period": "自由記述"},  # 解釈不能は寄与しない
    ]
    by_child = rs.covered_until_by_child(records)
    assert by_child == {"Aちゃん": date(2026, 9, 30), "Cちゃん": date(2026, 6, 30)}


def test_class_monthly_seed_inputs_without_records_includes_all_diaries(db):
    """経過記録が1件も無ければ全日誌が未反映（年度初〜前月末）＝境界なしの安全側。"""
    rs.save_document("diary", _diary_entry("2026-06-20"), author_kind="caregiver", now=_NOW)
    rs.save_document("diary", _diary_entry("2026-07-10"), author_kind="caregiver", now=_NOW)
    rs.save_document("diary", _diary_entry("2026-08-01"), author_kind="caregiver", now=_NOW)
    seed = rs.class_monthly_seed_inputs("0-2", "2026-08")
    # 対象月（8月）の日誌は seed に含めない（前月末カット）。
    assert [e["date"] for e in seed["class_diary_entries"]] == ["2026-06-20", "2026-07-10"]
    assert seed["class_record_entries"] == []
    assert seed["past_class_plans"] == []


def test_class_monthly_seed_inputs_invalid_month_fails_loud(db):
    """month 不正は ValueError（黙って誤解釈しない＝呼び出し側が降格/400 を決める）。"""
    with pytest.raises(ValueError):
        rs.class_monthly_seed_inputs("0-2", "でたらめ")


def test_class_roster_lists_children_of_the_age_band_with_age_labels(db):
    """在籍児名簿＝seed と同じ分類（年度4/1時点の年齢帯）＋対象月1日時点の月齢ラベル・表示名順。"""
    cid = rs.upsert_class("ひよこ組", "2026", now=_NOW)["id"]
    rs.upsert_child(
        "はるとくん", given_name="はると", gender="male", birthdate=date(2025, 4, 10), now=_NOW
    )
    rs.upsert_child(
        "さくらちゃん", given_name="さくら", gender="female", birthdate=date(2022, 5, 1), now=_NOW
    )
    rs.upsert_child("ゆいちゃん", given_name="ゆい", gender="female", now=_NOW)  # 生年月日未登録
    for name in ("はるとくん", "さくらちゃん", "ゆいちゃん"):
        rs.assign_child_to_class(name, cid, now=_NOW)
    roster = rs.class_roster("0-2", "2026-08")
    assert roster == [
        {"child_id": "はるとくん", "age_months": "1歳3か月", "class_name": "ひよこ組"}
    ]
    # 3–5 側には さくらちゃん だけ（生年月日未登録の児は年齢帯を推測せずどちらにも出さない）。
    assert [r["child_id"] for r in rs.class_roster("3-5", "2026-08")] == ["さくらちゃん"]


def test_class_roster_includes_midyear_newborn(db):
    """年度4/1より後に生まれた途中入園の0歳児も名簿に載る（記録ゼロの新入園児を落とさない）。"""
    cid = rs.upsert_class("ひよこ組", "2026", now=_NOW)["id"]
    rs.upsert_child(
        "あおくん", given_name="あお", gender="male", birthdate=date(2026, 5, 10), now=_NOW
    )
    rs.assign_child_to_class("あおくん", cid, now=_NOW)
    roster = rs.class_roster("0-2", "2026-08")
    assert [r["child_id"] for r in roster] == ["あおくん"]
    assert roster[0]["age_months"] == "0歳2か月"  # 対象月 2026-08 の1日時点


def test_class_roster_empty_and_invalid_inputs(db, monkeypatch):
    """名簿未整備・未接続は空（呼び出し側が「名簿なし」を正直表示）。month 不正は fail-loud。"""
    assert rs.class_roster("0-2", "2026-08") == []
    with pytest.raises(ValueError):
        rs.class_roster("0-2", "でたらめ")
    monkeypatch.setattr(settings, "database_url", "")
    rs.reset_engine_cache()
    assert rs.class_roster("0-2", "2026-08") == []


def test_class_monthly_seed_inputs_include_class_roster(db):
    """seed 合成に④在籍児名簿が載る（クラス・園児マスタ→クラス月案の与件・0–2 個人目標の対象）。"""
    cid = rs.upsert_class("ひよこ組", "2026", now=_NOW)["id"]
    rs.upsert_child(
        "はるとくん", given_name="はると", gender="male", birthdate=date(2025, 4, 10), now=_NOW
    )
    rs.assign_child_to_class("はるとくん", cid, now=_NOW)
    seed = rs.class_monthly_seed_inputs("0-2", "2026-08")
    assert [r["child_id"] for r in seed["class_roster"]] == ["はるとくん"]


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


# ──────────────────────────── users（Google identity の auto-provision・Phase 3） ────────────────────────────


def test_touch_user_provisions_and_is_idempotent(db):
    r1 = rs.touch_user("sensei@example.com", now=_NOW)
    assert r1 == {
        "status": "ok",
        "email": "sensei@example.com",
        "display_name": "",
        "active": True,
        "workspace_id": r1["workspace_id"],
        # 初回＝新規 workspace を作った呼び出しだけ True（デフォルト seed の単発トリガ）。
        "workspace_created": True,
    }
    r2 = rs.touch_user("sensei@example.com", now=_NOW)  # 2回目も同じ行（重複を作らない）
    assert r2["status"] == "ok"
    assert r2["workspace_id"] == r1["workspace_id"]
    assert r2["workspace_created"] is False
    with rs.Session(rs._engine()) as session:
        emails = [u.email for u in session.scalars(rs.sa.select(rs.User))]
    assert emails == ["sensei@example.com"]


def test_workspace_isolates_same_child_name_and_documents(db):
    """同じ児童表示名・同じ日付でも別 workspace の書類は相互に見えない。"""
    one = rs.touch_user("one@example.com", google_subject="subject-one", now=_NOW)["workspace_id"]
    two = rs.touch_user("two@example.com", google_subject="subject-two", now=_NOW)["workspace_id"]
    first = rs.save_document("diary", _diary_entry("2026-07-01"), workspace_id=one, now=_NOW)
    second = rs.save_document("diary", _diary_entry("2026-07-01"), workspace_id=two, now=_NOW)
    assert first["document_id"] != second["document_id"]
    assert len(rs.list_documents(workspace_id=one)) == 1
    assert len(rs.list_documents(workspace_id=two)) == 1
    assert rs.get_document(first["document_id"], workspace_id=two) is None
    assert [c["display_name"] for c in rs.list_children(workspace_id=one)] == [
        "はるとくん",
        "めいちゃん",
    ]
    assert rs.list_child_record_entries("はるとくん", workspace_id=two) == []


def test_workspace_deletion_request_is_idempotent(db):
    first = rs.request_workspace_deletion(
        "sensei@example.com", google_subject="subject-delete", now=_NOW
    )
    second = rs.request_workspace_deletion(
        "sensei@example.com", google_subject="subject-delete", now=_NOW
    )
    assert first["status"] == "pending"
    assert second == first
    assert first["due_at"].startswith("2026-08-04")


def test_process_due_deletion_removes_workspace_data(db):
    user = rs.touch_user("delete@example.com", google_subject="subject-due", now=_NOW)
    workspace = user["workspace_id"]
    rs.save_document("diary", _diary_entry("2026-07-01"), workspace_id=workspace, now=_NOW)
    rs.request_workspace_deletion(
        "delete@example.com", google_subject="subject-due", now=_NOW, retention_days=0
    )
    assert rs.process_due_deletion_requests(now=_NOW) == {"status": "ok", "processed": 1}
    assert rs.list_documents(workspace_id=workspace) == []
    with rs.Session(rs._engine()) as session:
        assert (
            session.scalar(
                rs.sa.select(rs.Workspace).where(rs.Workspace.id == uuid.UUID(workspace))
            )
            is None
        )


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


def test_age_months_label_basic():
    # 生年月日から期末（基準日）時点の満年齢を「○歳○か月」で返す（書式は下書き/シードと一致）。
    assert rs.age_months_label(date(2021, 4, 10), date(2026, 6, 30)) == "5歳2か月"
    assert rs.age_months_label(date(2024, 11, 20), date(2026, 6, 30)) == "1歳7か月"
    # 0 か月・0 歳も明示する（例 "2歳0か月" / "0歳3か月"）。
    assert rs.age_months_label(date(2024, 6, 25), date(2026, 6, 25)) == "2歳0か月"
    assert rs.age_months_label(date(2026, 3, 1), date(2026, 6, 30)) == "0歳3か月"


def test_age_months_label_day_boundary_rolls_back_month():
    # 基準日の「日」が誕生日の「日」に満たなければ月を1つ繰り下げる（暦どおりの満年齢）。
    assert rs.age_months_label(date(2024, 6, 25), date(2026, 6, 24)) == "1歳11か月"


def test_age_months_label_before_birth_is_empty():
    # 基準日が生年月日より前（まだ生まれていない）は空文字＝誤表示より無表示。
    assert rs.age_months_label(date(2027, 1, 1), date(2026, 6, 30)) == ""


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
    # 全角チルダ U+FF5E（Windows IME 既定で最頻出）・EN DASH も区切りとして受ける（取込・手入力の表記ゆれ）。
    assert rs.period_date_range("2026-04～2026-06") == (date(2026, 4, 1), date(2026, 6, 30))
    assert rs.period_date_range("2026-04–2026-06") == (date(2026, 4, 1), date(2026, 6, 30))
    # 移行前データ互換：月〜月以外は None（黙って誤解釈せず呼び出し側が安全側へ降格）。
    assert rs.period_date_range("1学期") is None
    assert rs.period_date_range("2026-06〜2026-04") is None  # 逆転も None


def test_normalize_month_zero_pads_or_raises():
    assert rs.normalize_month("2026-7") == "2026-07"
    assert rs.normalize_month("2026-07") == "2026-07"
    assert rs.normalize_month(" 2026-12 ") == "2026-12"
    for bad in ("2026", "2026/07", "2026-13", "令和8年7月", ""):
        with pytest.raises(ValueError):
            rs.normalize_month(bad)


def test_month_is_normalized_so_dedupe_and_ordering_hold(db):
    """非ゼロ詰め月（"2026-7"）でも target_month はゼロ詰めに揃い、同月の版が分裂しない・辞書順比較が効く。"""
    a = {"month": "2026-7", "child_id": "はるとくん", "age_band": "0-2"}
    b = {"month": "2026-07", "child_id": "はるとくん", "age_band": "0-2"}
    assert rs.save_document("monthly", a, author_kind="ai", now=_NOW)["status"] == "saved"
    assert rs.save_document("monthly", b, author_kind="caregiver", now=_NOW)["status"] == "saved"
    # "2026-7" と "2026-07" は同一書類（版が積まれる）＝dedupe_key が分裂しない。
    assert len([d for d in rs.list_documents() if d["doc_type"] == "monthly"]) == 1
    # クラス月案の履歴 seed も "2026-7" の before_month で July 自身を除外できる（辞書順比較の前提を守る）。
    rs.save_document(
        "class_monthly", {"month": "2026-7", "age_band": "0-2", "monthly_goal": "g"}, now=_NOW
    )
    rs.save_document(
        "class_monthly", {"month": "2026-06", "age_band": "0-2", "monthly_goal": "g"}, now=_NOW
    )
    plans = rs.list_class_monthly_entries("0-2", before_month="2026-7")
    assert [p["month"] for p in plans] == ["2026-06"]  # July 自身は含まれない


def test_approve_version_conflict_and_audit_detail(db):
    """編集→承認の競合：expected_version_seq が現行版と食い違えば承認を拒否し、証跡に版番号を残す。"""
    entry = _diary_entry("2026-07-03")
    rs.save_document("diary", entry, author_kind="ai", now=_NOW)  # v1
    rs.save_document("diary", entry, author_kind="caregiver", now=_NOW)  # v2（別編集が積まれた）
    # 保育士が v1 を見たまま承認 → 現行は v2 なので拒否（取り違え防止）。
    stale = rs.approve_document("diary", entry, actor="A", now=_NOW, expected_version_seq=1)
    assert stale["status"] == "error" and stale["code"] == "version_conflict"
    assert rs.list_documents()[0]["status"] != "approved"
    # 現行版（v2）を指定すれば承認でき、証跡に承認した版番号が残る（save と対称）。
    ok = rs.approve_document("diary", entry, actor="園長", now=_NOW, expected_version_seq=2)
    assert ok["status"] == "approved" and ok["version_seq"] == 2
    approve_events = [e for e in rs.list_audit_events() if e["action"] == "approve"]
    assert approve_events and approve_events[-1]["detail"].get("version_seq") == 2


def test_write_error_generic_for_db_failure_but_detail_for_input(db):
    """入力 ValueError は安全な文言をそのまま返し、DB 障害（SQLAlchemyError）は一般化して SQL を露出しない。"""
    import sqlalchemy as _sa

    # 入力エラー（date 欠落）＝原因が分かる文言を保育士へ返す。
    r = rs.save_document("diary", {"age_band": "0-2"}, author_kind="ai", now=_NOW)
    assert r["status"] == "error" and "date" in r["detail"]
    # DB 障害＝raw str(exc)（SQL 文・投入値）を返さず一般化＋コード。
    err = rs._write_error(_sa.exc.SQLAlchemyError("[SQL: INSERT …] [parameters: ('秘密',)]"))
    assert err["code"] == "db_write_failed"
    assert "SQL" not in err["detail"] and "秘密" not in err["detail"]


def test_actor_is_clamped_to_column_width(db):
    """正当に長い担当者名（Google 表示名＋email 等）でも VARCHAR(100) を超えず保存できる（PG で落ちない）。"""
    long_actor = "あ" * 250
    entry = _diary_entry("2026-07-09")
    rs.save_document("diary", entry, author_kind="caregiver", actor=long_actor, now=_NOW)
    rs.approve_document("diary", entry, actor=long_actor, now=_NOW)
    stored = {e["actor"] for e in rs.list_audit_events()}
    assert stored == {long_actor[:100]}
    assert all(len(a) <= 100 for a in stored)


# ──────────────────────────── クラス（組）マスタ・所属（名簿管理・日誌 roster の素） ────────────────────────────


def test_upsert_class_creates_and_is_idempotent_by_name_and_year(db):
    r = rs.upsert_class("ひまわり組", "2026", now=_NOW)
    assert r["status"] == "created"
    assert (r["name"], r["fiscal_year"], r["age_bands"]) == ("ひまわり組", "2026", [])
    # 同じ組名＋年度は既存（重複を作らない）。
    r2 = rs.upsert_class("ひまわり組", "2026", now=_NOW)
    assert r2["status"] == "exists"
    # 同じ組名でも年度違いは別クラス（進級で組名を再利用できる）。
    r3 = rs.upsert_class("ひまわり組", "2027", now=_NOW)
    assert r3["status"] == "created" and r3["id"] != r["id"]
    names = [(c["name"], c["fiscal_year"]) for c in rs.list_classes(active_only=True)]
    assert ("ひまわり組", "2026") in names and ("ひまわり組", "2027") in names


def test_class_age_bands_are_derived_from_roster(db):
    cid = rs.upsert_class("たんぽぽ組", "2026", now=_NOW)["id"]
    rs.upsert_child(
        "ゆいちゃん", given_name="ゆい", gender="female", birthdate=date(2023, 4, 2), now=_NOW
    )
    rs.upsert_child(
        "さくらちゃん", given_name="さくら", gender="female", birthdate=date(2021, 4, 2), now=_NOW
    )
    rs.assign_child_to_class("ゆいちゃん", cid, now=_NOW)
    rs.assign_child_to_class("さくらちゃん", cid, now=_NOW)
    cls = next(c for c in rs.list_classes() if c["id"] == cid)
    assert cls["age_bands"] == ["0-2", "3-5"]


def test_upsert_class_degrades_without_a_database(monkeypatch, db):
    assert rs.upsert_class("", "2026", now=_NOW)["status"] == "skipped"  # 空名
    monkeypatch.setattr(settings, "database_url", "")
    rs.reset_engine_cache()
    assert rs.upsert_class("ばら組", "2026", now=_NOW)["status"] == "skipped"  # 未接続


def test_assign_child_to_class_and_roster(db):
    cid = rs.upsert_class("さくら組", "2026", now=_NOW)["id"]
    rs.upsert_child("はるとくん", given_name="はると", gender="male", now=_NOW)
    rs.upsert_child("ゆいちゃん", given_name="ゆい", gender="female", now=_NOW)
    assert rs.assign_child_to_class("はるとくん", cid, now=_NOW)["status"] == "ok"
    assert rs.assign_child_to_class("ゆいちゃん", cid, now=_NOW)["status"] == "ok"
    # roster＝クラスの在籍児（表示名順）。年齢帯はクラスでなく生年月日から導出する。
    roster = rs.list_children_in_class(cid)
    assert [c["display_name"] for c in roster] == ["はるとくん", "ゆいちゃん"]
    assert roster[0]["class_name"] == "さくら組"
    # list_children にも所属が乗る（名簿UIのグループ化）。
    haruto = next(c for c in rs.list_children() if c["display_name"] == "はるとくん")
    assert haruto["class_id"] == cid and haruto["class_name"] == "さくら組"
    # 在籍児数の集計。
    assert next(c for c in rs.list_classes() if c["id"] == cid)["child_count"] == 2


def test_assign_child_unassign_and_error_paths(db):
    cid = rs.upsert_class("もも組", "2026", now=_NOW)["id"]
    rs.upsert_child("そうたくん", given_name="そうた", gender="male", now=_NOW)
    rs.assign_child_to_class("そうたくん", cid, now=_NOW)
    # None/"" で未所属へ戻す。
    assert rs.assign_child_to_class("そうたくん", None, now=_NOW)["status"] == "ok"
    assert (
        next(c for c in rs.list_children() if c["display_name"] == "そうたくん")["class_id"] is None
    )
    # 不正 id・未登録児・不在クラスは error（黙って握りつぶさない）。
    assert rs.assign_child_to_class("そうたくん", "not-a-uuid", now=_NOW)["status"] == "error"
    assert rs.assign_child_to_class("いないくん", cid, now=_NOW)["status"] == "error"
    assert (
        rs.assign_child_to_class("そうたくん", "00000000-0000-0000-0000-000000000000", now=_NOW)[
            "status"
        ]
        == "error"
    )


def test_class_reads_degrade_when_url_unset(monkeypatch):
    monkeypatch.setattr(settings, "database_url", "")
    rs.reset_engine_cache()
    assert rs.list_classes() == []
    assert rs.list_children_in_class("x") == []
    assert rs.upsert_class("ひまわり組", "2026", now=_NOW)["status"] == "skipped"
    assert rs.assign_child_to_class("はるとくん", None, now=_NOW)["status"] == "skipped"


# ──────────────────────────── フィードバック（👍👎＋ひとこと） ────────────────────────────


def test_save_feedback_links_to_document_and_current_version(db):
    """👍👎＋ひとことは対象書類＋送信時点の現行版に紐付いて保存される（version_seq を返す）。"""
    entry = _diary_entry("2026-07-01")
    saved = rs.save_document("diary", entry, author_kind="ai", now=_NOW)
    doc_id = saved["document_id"]
    r = rs.save_feedback(doc_id, "down", "もう少し具体的に", actor="保育士A", now=_NOW)
    assert r["status"] == "saved"
    assert r["document_id"] == doc_id
    assert r["version_seq"] == 1  # AI 確定版（seq 1）への評価
    fbs = rs.list_feedback(doc_id)
    assert len(fbs) == 1
    assert fbs[0]["verdict"] == "down"
    assert fbs[0]["comment"] == "もう少し具体的に"
    assert fbs[0]["actor"] == "保育士A"
    assert fbs[0]["version_seq"] == 1


def test_save_feedback_tracks_the_version_seen(db):
    """後で編集して版が進んでも、フィードバックは評価した版（seq）に紐付いたまま残る。"""
    later = datetime(2026, 7, 5, 18, 5, 0)  # 2つ目の送信は別時刻（新しい順の並びを決定的に）
    entry = _diary_entry("2026-07-02")
    doc_id = rs.save_document("diary", entry, author_kind="ai", now=_NOW)["document_id"]
    rs.save_feedback(doc_id, "up", "この観察が良い", now=_NOW)  # seq 1 への 👍
    rs.save_document(
        "diary", dict(entry, daily_aim="修正後"), author_kind="caregiver", now=_NOW
    )  # seq 2
    rs.save_feedback(doc_id, "down", "まだ気になる", now=later)  # seq 2 への 👎
    fbs = rs.list_feedback(doc_id)  # 新しい順
    assert [f["version_seq"] for f in fbs] == [2, 1]
    assert [f["verdict"] for f in fbs] == ["down", "up"]


def test_save_feedback_rejects_bad_verdict_and_missing_document(db):
    entry = _diary_entry("2026-07-03")
    doc_id = rs.save_document("diary", entry, author_kind="ai", now=_NOW)["document_id"]
    assert rs.save_feedback(doc_id, "meh", "", now=_NOW)["status"] == "error"  # verdict 語彙外
    assert rs.save_feedback("not-a-uuid", "up", "", now=_NOW)["status"] == "error"  # 不正 id
    missing = "00000000-0000-0000-0000-000000000000"
    assert rs.save_feedback(missing, "up", "", now=_NOW)["status"] == "error"  # 対象不在


def test_feedback_degrades_when_url_unset(monkeypatch):
    monkeypatch.setattr(settings, "database_url", "")
    rs.reset_engine_cache()
    # DB 未接続でも保存は本流を壊さず skipped（改善フロー自体は別途動く）・読取は空。
    assert rs.save_feedback("x", "up", "コメント", now=_NOW)["status"] == "skipped"
    assert rs.list_feedback() == []
