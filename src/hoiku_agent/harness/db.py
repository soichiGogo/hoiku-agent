"""harness 共通の DB 接続基盤（Cloud SQL PostgreSQL・テストは sqlite）。

`record_store`（書類アーカイブ・Phase 1）と `policy_store`（育つ指針＝カードブック・Phase 2 統合）が
同じ `DATABASE_URL` の engine と Declarative Base を共有するための最小インフラ。
ここには**接続とモデル台帳（Base.metadata）だけ**を置き、ドメインの決定的ロジックは置かない
（各ストアの責務は record_store / policy_store に1つずつ＝§5）。

- 接続 URL は config.settings.database_url が唯一の出所（未設定は None＝各ストアが降格）。
- engine は URL 別にキャッシュ（Cloud Run の並行リクエストでも素直に働く控えめなプール）。
- スキーマ適用は repo root の Alembic（migrations/・env.py が本 Base.metadata を見る）。
"""

from __future__ import annotations

from collections.abc import Iterable

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import DeclarativeBase

# PostgreSQL では JSONB、テスト（sqlite）では素の JSON にフォールバックする。
JSON_VARIANT = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


class Base(DeclarativeBase):
    pass


_ENGINES: dict[str, sa.Engine] = {}


def database_url() -> str:
    """接続 URL（未設定は空文字＝降格）。config が唯一の出所。"""
    from ..config import settings  # 遅延 import（テストの monkeypatch・循環回避）

    return settings.database_url.strip()


def engine() -> sa.Engine | None:
    url = database_url()
    if not url:
        return None
    if url not in _ENGINES:
        _ENGINES[url] = sa.create_engine(url, pool_pre_ping=True)
    return _ENGINES[url]


def reset_engine_cache() -> None:
    """テスト用：URL 差し替え後に engine キャッシュを破棄する。"""
    for eng in _ENGINES.values():
        eng.dispose()
    _ENGINES.clear()


# --- スキーマ整合の観測（migration drift の可視化・§ prod-db-migration-drift） -------------------
# ここはドメインロジックではなく接続基盤の観測：新しい migration を本番 DB に上げ忘れると（CD が
# 自動適用しても手動 gcloud 等で経路が外れると）テーブル欠落が record_store を fail-loud で落とし、
# 保育士に生の 500 を見せる。それを「起動時に気づける」「素の stack trace でなく明快な応答にする」ための
# 純粋な補助。判定ロジックは決定的で、tests/test_harness から creds 不要にテストできる。


def is_missing_schema_error(exc: BaseException | None) -> bool:
    """例外が「テーブル/カラム不在」（＝migration 未適用の典型）かをドライバ非依存に判定する。

    Postgres(psycopg) は `UndefinedTable`/`UndefinedColumn`、sqlite は "no such table/column"。
    SQLAlchemy は DBAPI 例外を `.orig` に包むため orig/__cause__ の連鎖も辿る（循環は id で防ぐ）。
    """
    seen: set[int] = set()
    cur: BaseException | None = exc
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        if type(cur).__name__ in ("UndefinedTable", "UndefinedColumn"):
            return True
        msg = str(cur).lower()
        if any(
            k in msg
            for k in ("no such table", "no such column", "undefinedtable", "undefinedcolumn")
        ):
            return True
        cur = getattr(cur, "orig", None) or getattr(cur, "__cause__", None)
    return False


def missing_tables(existing: Iterable[str], expected: Iterable[str]) -> list[str]:
    """期待テーブルのうち実 DB(existing) に無いものを整列して返す（純関数）。"""
    have = set(existing)
    return sorted(t for t in set(expected) if t not in have)


def schema_drift() -> list[str]:
    """DB 接続時、ORM 台帳(Base.metadata) に対し実 DB に不足するテーブル名を返す。

    DATABASE_URL 未設定（降格）・到達不能・点検失敗時は空リスト（観測は best-effort＝起動を止めない）。
    全ストアのモデルを import してから台帳を読む（遅延 import で循環回避）。
    """
    eng = engine()
    if eng is None:
        return []
    # record_store / policy_store / notation_store / template_store のモデルを Base.metadata へ登録。
    from . import notation_store, policy_store, record_store, template_store  # noqa: F401

    try:
        existing = sa.inspect(eng).get_table_names()
    except Exception:
        return []
    return missing_tables(existing, Base.metadata.tables.keys())
