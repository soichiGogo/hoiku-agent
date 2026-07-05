"""テスト全体の共通フィクスチャ。

開発者の `.env`（DATABASE_URL 等）がテストへ漏れて実 DB（Cloud SQL）に触れないよう、
ストレージ設定を既定で空にする（各テストは必要時に fixture 内で上書きする）。
"""

from __future__ import annotations

import pytest

from hoiku_agent.config import settings


@pytest.fixture(autouse=True)
def _isolate_database_url(monkeypatch):
    """ストレージ DB（書類アーカイブ＋指針カードブック）をテストから隔離する（既定＝降格/ローカル経路）。"""
    monkeypatch.setattr(settings, "database_url", "")


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
