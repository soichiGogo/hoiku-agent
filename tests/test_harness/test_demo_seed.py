"""harness/demo_seed（デフォルト seed・データ初期化）の単体テスト（LLM/GCP creds 不要・決定論）。

初回ログインの auto-seed（web/workspace.py）と「データを初期化」（web /api/account/reset）の
決定的実体を sqlite で検証する：全 entry の型成立・冪等投入・workspace 境界・
purge が User/Workspace を残すこと・reset の往復。
"""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest

from hoiku_agent.config import settings
from hoiku_agent.harness import demo_seed, record_store as rs
from hoiku_agent.harness import demo_seed_data as data

_NOW = datetime(2026, 7, 12, 9, 0, 0)
_TOTAL_DOCS = sum(len(entries) for _, entries in data.JOBS)


@pytest.fixture()
def db(tmp_path, monkeypatch):
    """sqlite の一時 DB に向けてスキーマを作る（record_store のテストと同じ流儀）。"""
    url = f"sqlite:///{tmp_path}/archive.db"
    monkeypatch.setattr(settings, "database_url", url)
    rs.reset_engine_cache()
    engine = rs._engine()
    rs.Base.metadata.create_all(engine)
    yield url
    rs.reset_engine_cache()


def test_validate_all_ok() -> None:
    """全 seed 書類が型成立（旧 seed script の投入前検査を CI に常設化）。"""
    assert demo_seed.validate_all() == []


def test_unapproved_keys_exist_in_data() -> None:
    """UNAPPROVED のキーが実データに存在する（改名・期間変更で silent に全承認へ倒れない）。"""
    keys = {(k, data.child_of(k, e), data.target_of(k, e)) for k, es in data.JOBS for e in es}
    assert data.UNAPPROVED <= keys


# ──────────────────────────── データ整合（生年月日・登場・平日・実名ガード） ────────────────────────────

_FICTIONAL = set(name for name, _ in data.ROSTER) | {data.GRADUATE}


def test_only_fictional_children() -> None:
    """登場児は名簿10人＋卒園児の閉集合のみ（実名・未知名の混入ガード＝§14）。"""
    seen: set[str] = set()
    for _, entries in data.JOBS:
        for e in entries:
            for note in e.get("individual_notes", []):
                seen.add(note["child_id"])
            for att in e.get("attendance", []):
                seen.add(att["child_id"])
            for g in e.get("individual_goals", []):
                seen.add(g["child_id"])
            if e.get("child_id"):
                seen.add(e["child_id"])
    assert seen <= _FICTIONAL, f"名簿外の児が混入: {seen - _FICTIONAL}"


def test_age_months_match_birthdate() -> None:
    """全書類の月齢表記が生年月日から再計算した値と一致する（手書きずれのガード）。"""
    from datetime import date

    def check(child: str, on: date, shown: str) -> None:
        assert data.age_months_on(child, on) == shown, f"{child} {on}: {shown}"

    for e in data.DIARIES:
        on = date.fromisoformat(e["date"])
        for note in e["individual_notes"]:
            check(note["child_id"], on, note["age_months"])


def test_diaries_are_weekdays_only() -> None:
    """日誌は平日のみ（土日祝に日誌がない＝毎日書くものの現実に合わせる）。"""
    from datetime import date

    for e in data.DIARIES:
        d = date.fromisoformat(e["date"])
        assert d.weekday() < 5, f"土日に日誌: {e['date']}"
        assert d not in data.HOLIDAYS, f"祝日に日誌: {e['date']}"


def test_every_child_appears_in_diaries_each_month() -> None:
    """名簿の全員が毎月、日誌の個別記録に登場する（誰を選んでも物語が見える）。"""
    from collections import defaultdict

    seen: dict[str, set[str]] = defaultdict(set)  # child -> {"YYYY-MM"}
    for e in data.DIARIES:
        month = e["date"][:7]
        for note in e["individual_notes"]:
            seen[note["child_id"]].add(month)
    months = {"2026-04", "2026-05", "2026-06", "2026-07"}
    for name, _ in data.ROSTER:
        assert months <= seen[name], f"{name} が登場しない月: {months - seen[name]}"


def test_hiyoko_individual_goals_cover_all_members() -> None:
    """ひよこ組（0-2）のクラス月案は在籍5人全員の個人目標を持つ（§18）。"""
    for plan in data.CLASS_MONTHLY_PLANS:
        if plan["age_band"] != "0-2":
            continue
        ids = {g["child_id"] for g in plan.get("individual_goals", [])}
        assert set(data.HIYOKO) == ids, f"{plan['month']}: {ids}"


def test_seed_workspace_populates_roster_classes_documents(db) -> None:
    result = demo_seed.seed_workspace(None, now=_NOW)
    assert result["status"] == "ok"
    assert result["children"] == len(data.ROSTER)
    assert result["classes"] == len(data.CLASSES)
    assert result["documents"] == _TOTAL_DOCS
    # 承認は「型成立かつ UNAPPROVED 外」だけ＝未記入の直近日誌（is_incomplete）は自動的に finalized。
    assert result["approved"] == _approved_expected()

    # クラス2つ＋年齢帯どおりの割当（はると/つむぎ=年長→あおぞら、めい=1歳児→ひよこ）
    classes = {c["name"]: c for c in rs.list_classes()}
    assert set(classes) == {"ひよこ組", "あおぞら組"}
    aozora = {c["display_name"] for c in rs.list_children_in_class(classes["あおぞら組"]["id"])}
    hiyoko = {c["display_name"] for c in rs.list_children_in_class(classes["ひよこ組"]["id"])}
    assert {"はるとくん", "つむぎちゃん"} <= aozora
    assert "めいちゃん" in hiyoko
    assert len(aozora) + len(hiyoko) == len(data.ROSTER)  # 全員がどちらかに所属

    # 状態は approved か finalized の2値（finalized は UNAPPROVED か is_incomplete のいずれか）。
    docs = [d for kind, _ in data.JOBS for d in rs.list_documents(kind, limit=5000)]
    assert len(docs) == _TOTAL_DOCS
    assert {d["status"] for d in docs} == {"approved", "finalized"}


def _approved_expected() -> int:
    """承認されるべき件数＝型成立かつ UNAPPROVED 外の書類数（未記入日誌・未承認指定を除く）。"""
    from hoiku_agent.harness.finalize import finalize_entry

    n = 0
    for kind, entries in data.JOBS:
        for e in entries:
            key = (kind, data.child_of(kind, e), data.target_of(kind, e))
            if key in data.UNAPPROVED:
                continue
            if finalize_entry(e, kind=kind).ok:
                n += 1
    return n


def test_incomplete_diaries_saved_but_unapproved(db) -> None:
    """評価未記入の直近日誌（記入導線デモ）は保存されるが finalized 止まり＝承認されない。"""
    from datetime import date

    demo_seed.seed_workspace(None, now=_NOW)
    meta = rs.list_diary_meta(date(2026, 7, 1), date(2026, 7, 10))
    incomplete = [m for m in meta if not m["evaluation_complete"]]
    # 2026-07-09/07-10 × 両クラス＝4件が「評価未記入」として検出できる（記入導線のデモ）
    assert len(incomplete) == 4
    assert all(m["status"] == "finalized" for m in incomplete)


def test_seed_workspace_idempotent(db) -> None:
    """再実行しても版が増えない（初回ログインの並行リクエスト・途中失敗後の再実行に安全）。"""
    demo_seed.seed_workspace(None, now=_NOW)
    second = demo_seed.seed_workspace(None, now=_NOW)
    assert second["status"] == "ok"
    assert second["documents"] == 0  # 全件スキップ＝新規保存なし
    docs = [d for kind, _ in data.JOBS for d in rs.list_documents(kind, limit=5000)]
    assert len(docs) == _TOTAL_DOCS


def test_seed_workspace_scoped(db) -> None:
    """seed は指定 workspace にだけ入る（他 workspace・ローカル既定領域へ漏れない）。"""
    target = str(uuid.uuid4())
    demo_seed.seed_workspace(target, now=_NOW)
    assert rs.list_children(workspace_id=target)
    assert rs.list_children() == []  # ローカル既定領域は空のまま
    assert rs.list_documents("diary", limit=10) == []


def test_seed_workspace_degrades_without_db(monkeypatch) -> None:
    monkeypatch.setattr(settings, "database_url", "")
    rs.reset_engine_cache()
    assert demo_seed.seed_workspace(None, now=_NOW)["status"] == "skipped"
    assert demo_seed.reset_workspace(None, now=_NOW)["status"] == "skipped"


def test_purge_workspace_data_keeps_user_and_workspace(db) -> None:
    """purge はデータ行だけ消し、User/Workspace（＝ログイン）を残す（アカウント削除とは別物）。"""
    user = rs.touch_user("sensei@example.com", google_subject="sub-1", now=_NOW)
    workspace_id = user["workspace_id"]
    demo_seed.seed_workspace(workspace_id, now=_NOW)
    assert rs.list_children(workspace_id=workspace_id)

    assert rs.purge_workspace_data(workspace_id)["status"] == "ok"
    assert rs.list_children(workspace_id=workspace_id) == []
    assert rs.list_classes(workspace_id=workspace_id) == []
    assert all(
        rs.list_documents(kind, limit=10, workspace_id=workspace_id) == [] for kind, _ in data.JOBS
    )
    # User 行は残り、再ログインで同じ workspace が返る（workspace_created は立たない）
    again = rs.touch_user("sensei@example.com", google_subject="sub-1", now=_NOW)
    assert again["workspace_id"] == workspace_id
    assert again["workspace_created"] is False


def test_reset_workspace_restores_seed(db) -> None:
    """reset＝消去→seed 再投入（保育士の追加データが消え、初期状態に戻る）。"""
    workspace_id = str(uuid.uuid4())
    demo_seed.seed_workspace(workspace_id, now=_NOW)
    rs.upsert_child("テスト追加くん", workspace_id=workspace_id, now=_NOW)
    assert len(rs.list_children(workspace_id=workspace_id)) == len(data.SEEDED_CHILDREN) + 1

    result = demo_seed.reset_workspace(workspace_id, now=_NOW)
    assert result["status"] == "ok" and result["purged"] is True
    names = {c["display_name"] for c in rs.list_children(workspace_id=workspace_id)}
    assert "テスト追加くん" not in names  # 保育士の追加は消える
    assert names == set(data.SEEDED_CHILDREN)  # 名簿10人＋卒園児（要録の登場児）に戻る
    docs = [
        d
        for kind, _ in data.JOBS
        for d in rs.list_documents(kind, limit=5000, workspace_id=workspace_id)
    ]
    assert len(docs) == _TOTAL_DOCS
