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
