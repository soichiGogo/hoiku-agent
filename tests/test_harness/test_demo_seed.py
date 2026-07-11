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


def test_seed_workspace_populates_roster_classes_documents(db) -> None:
    result = demo_seed.seed_workspace(None, now=_NOW)
    assert result["status"] == "ok"
    assert result["children"] == len(data.ROSTER)
    assert result["classes"] == len(data.CLASSES)
    assert result["documents"] == _TOTAL_DOCS
    assert result["approved"] == _TOTAL_DOCS - len(data.UNAPPROVED)

    # クラス2つ＋年齢帯どおりの割当（はると/つむぎ=2021生→あおぞら、めい=2024-04生→ひよこ）
    classes = {c["name"]: c for c in rs.list_classes()}
    assert set(classes) == {"ひよこ組", "あおぞら組"}
    aozora = {c["display_name"] for c in rs.list_children_in_class(classes["あおぞら組"]["id"])}
    hiyoko = {c["display_name"] for c in rs.list_children_in_class(classes["ひよこ組"]["id"])}
    assert {"はるとくん", "つむぎちゃん"} <= aozora
    assert "めいちゃん" in hiyoko
    assert len(aozora) + len(hiyoko) == len(data.ROSTER)  # 全員がどちらかに所属

    # UNAPPROVED だけ finalized 止まり・残りは approved
    docs = [d for kind, _ in data.JOBS for d in rs.list_documents(kind, limit=5000)]
    assert len(docs) == _TOTAL_DOCS
    by_key = {(d["doc_type"], d["child"], d["target"]): d["status"] for d in docs}
    for key, status in by_key.items():
        assert status == ("finalized" if key in data.UNAPPROVED else "approved"), key


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
    assert len(rs.list_children(workspace_id=workspace_id)) == len(data.ROSTER) + 1

    result = demo_seed.reset_workspace(workspace_id, now=_NOW)
    assert result["status"] == "ok" and result["purged"] is True
    names = {c["display_name"] for c in rs.list_children(workspace_id=workspace_id)}
    assert "テスト追加くん" not in names
    assert len(names) == len(data.ROSTER)
    docs = [
        d
        for kind, _ in data.JOBS
        for d in rs.list_documents(kind, limit=5000, workspace_id=workspace_id)
    ]
    assert len(docs) == _TOTAL_DOCS
