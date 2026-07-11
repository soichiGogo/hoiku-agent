"""テスト全体の共通フィクスチャ。

開発者の `.env`（DATABASE_URL 等）がテストへ漏れて実 DB（Cloud SQL）に触れないよう、
ストレージ設定を既定で空にする（各テストは必要時に fixture 内で上書きする）。
"""

from __future__ import annotations

import pytest

from hoiku_agent.config import settings


@pytest.fixture(autouse=True)
def _isolate_external_stores(monkeypatch):
    """開発者のDB/Memory Bank設定をテストから隔離する（明示fixtureだけが有効化）。"""
    monkeypatch.setattr(settings, "database_url", "")
    monkeypatch.setattr(settings, "agent_engine_id", "")


@pytest.fixture()
def policy_db(tmp_path, monkeypatch):
    """指針カードブックを sqlite の一時 DB へ向ける（creds 不要・決定的。test_policy_store / test_improver 共用）。

    ローカルシード（`_POLICY_PATH`）も一時ファイルへ差し替える＝「DB 行不在→ローカルシード」の
    フォールバックが repo の実シードに依存しないようにする（既定は空 book）。
    """
    from hoiku_agent.harness import db, policy_store as ps

    url = f"sqlite:///{tmp_path}/store.db"
    monkeypatch.setattr(settings, "database_url", url)
    monkeypatch.setattr(ps, "_POLICY_PATH", tmp_path / "seed.json")
    db.reset_engine_cache()
    db.Base.metadata.create_all(db.engine())
    yield url
    db.reset_engine_cache()


@pytest.fixture()
def notation_db(tmp_path, monkeypatch):
    """表記ルールブックを sqlite の一時 DB へ向ける（creds 不要・決定的。policy_db と対称）。

    ローカルシード（`_NOTATION_PATH`）も一時ファイルへ差し替える＝「DB 行不在→ローカルシード」の
    フォールバックが repo の実シードに依存しないようにする（既定は空 book）。
    """
    from hoiku_agent.harness import db, notation_store as ns

    url = f"sqlite:///{tmp_path}/notation.db"
    monkeypatch.setattr(settings, "database_url", url)
    monkeypatch.setattr(ns, "_NOTATION_PATH", tmp_path / "seed.json")
    db.reset_engine_cache()
    db.Base.metadata.create_all(db.engine())
    yield url
    db.reset_engine_cache()


@pytest.fixture()
def template_db(tmp_path, monkeypatch):
    """様式テンプレートブックを sqlite の一時 DB へ向ける（creds 不要・決定的。notation_db と対称）。

    ローカルシード（`_TEMPLATE_PATH`）も一時ファイルへ差し替える＝「DB 行不在→ローカルシード」の
    フォールバックが repo の実シードに依存しないようにする（既定は空 book）。
    """
    from hoiku_agent.harness import db, template_store as ts

    url = f"sqlite:///{tmp_path}/template.db"
    monkeypatch.setattr(settings, "database_url", url)
    monkeypatch.setattr(ts, "_TEMPLATE_PATH", tmp_path / "seed.json")
    db.reset_engine_cache()
    db.Base.metadata.create_all(db.engine())
    yield url
    db.reset_engine_cache()
