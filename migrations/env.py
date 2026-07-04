"""Alembic env：書類アーカイブ（harness/record_store）のスキーマ移行。

接続 URL は config.settings.database_url（.env / 環境変数の DATABASE_URL）が唯一の出所。
未設定なら明示エラーで止める（migration は「DB を使う」意思が前提＝降格しない）。
"""

from __future__ import annotations

import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import create_engine

# repo root の src/ を import path へ（pytest の pythonpath=["src","."] と同じ解決）。
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from hoiku_agent.config import settings  # noqa: E402
from hoiku_agent.harness.record_store import Base  # noqa: E402

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _url() -> str:
    url = settings.database_url.strip()
    if not url:
        raise SystemExit(
            "DATABASE_URL が未設定です（.env か環境変数に設定してから alembic を実行してください）"
        )
    return url


def run_migrations_offline() -> None:
    context.configure(url=_url(), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(_url())
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
