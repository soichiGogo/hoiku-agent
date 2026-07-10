"""DB スキーマ整合の観測ヘルパ（harness/db.py）の決定論テスト。

migration drift（新 migration の本番未適用＝欠落テーブル）を「起動時に気づく」「生の 500 でなく明快な
応答にする」ための純粋な判定を、creds 不要・sqlite で検証する（§ prod-db-migration-drift）。
"""

from __future__ import annotations

from hoiku_agent.config import settings
from hoiku_agent.harness import db


# ──────────────── is_missing_schema_error（テーブル/カラム不在の判定） ────────────────


class UndefinedTable(Exception):
    """psycopg.errors.UndefinedTable を型名で模す（判定は型名/メッセージで行うため中身は不要）。"""


class _Wrapper(Exception):
    """SQLAlchemy が DBAPI 例外を .orig に包む構造を模す。"""

    def __init__(self, orig: Exception) -> None:
        super().__init__("(wrapper) statement failed")
        self.orig = orig


def test_missing_schema_error_by_type_name() -> None:
    assert db.is_missing_schema_error(UndefinedTable("relation does not exist")) is True


def test_missing_schema_error_through_orig_chain() -> None:
    # 生の psycopg 例外を SQLAlchemy ラッパの .orig に包んでも辿れる。
    assert db.is_missing_schema_error(_Wrapper(UndefinedTable("x"))) is True


def test_missing_schema_error_by_sqlite_message() -> None:
    assert db.is_missing_schema_error(Exception("no such table: classes")) is True
    assert db.is_missing_schema_error(Exception("no such column: children.class_id")) is True


def test_non_schema_errors_are_not_flagged() -> None:
    assert db.is_missing_schema_error(Exception("connection refused")) is False
    assert db.is_missing_schema_error(ValueError("bad value")) is False
    assert db.is_missing_schema_error(None) is False


def test_missing_schema_error_survives_orig_cycle() -> None:
    """orig が自分を指す壊れた連鎖でも無限ループしない（id で打ち切り）。"""
    e = _Wrapper.__new__(_Wrapper)
    Exception.__init__(e, "connection reset")
    e.orig = e  # 自己参照
    assert db.is_missing_schema_error(e) is False


# ──────────────── missing_tables（純関数の集合差） ────────────────


def test_missing_tables_pure_diff() -> None:
    assert db.missing_tables({"a", "b"}, {"a", "b", "c"}) == ["c"]
    assert db.missing_tables({"a", "b", "c"}, {"a", "b"}) == []
    assert db.missing_tables([], ["z", "a", "m"]) == ["a", "m", "z"]  # 整列される


# ──────────────── schema_drift（実 DB を inspect） ────────────────


def test_schema_drift_empty_when_db_unset(monkeypatch) -> None:
    monkeypatch.setattr(settings, "database_url", "")
    db.reset_engine_cache()
    assert db.schema_drift() == []


def test_schema_drift_detects_missing_tables_then_clears(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{tmp_path}/drift.db")
    db.reset_engine_cache()
    # スキーマ未作成＝ORM 台帳の全テーブルが不足（クラス機能の classes を含む）。
    missing = db.schema_drift()
    assert "classes" in missing
    assert "documents" in missing
    # 台帳どおりに作れば drift は解消する。
    eng = db.engine()
    assert eng is not None
    db.Base.metadata.create_all(eng)
    assert db.schema_drift() == []
    db.reset_engine_cache()


def test_engine_returns_none_on_invalid_url(monkeypatch) -> None:
    """不正な URL（構築時に失敗するスキーム）は例外を伝播させず None 降格＝未接続扱い（各ストアの契約を守る）。

    record_store の読取は「降格＝空」・server.py の schema_drift は「起動を止めない」を謳うが、engine() が
    create_engine の失敗をそのまま投げると両方の契約が破れる（500・uvicorn 起動失敗）。None 降格で回復する。
    """
    monkeypatch.setattr(
        settings, "database_url", "postgres://user:pw@host/db"
    )  # 旧スキーム＝NoSuchModule
    db.reset_engine_cache()
    assert db.engine() is None
    assert db.schema_drift() == []  # engine None なので観測は空（起動を止めない）
    db.reset_engine_cache()
