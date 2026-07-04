"""テスト全体の共通フィクスチャ。

開発者の `.env`（POLICY_STORE_URI 等）がテストへ漏れて実 GCS に触れないよう、
外部ストア設定を既定で空にする（各テストは必要時に fixture 内で上書きする）。
"""

from __future__ import annotations

import pytest

from hoiku_agent.config import settings


@pytest.fixture(autouse=True)
def _isolate_policy_store_uri(monkeypatch):
    """policy_store の外部ストア（GCS）設定をテストから隔離する（既定＝ローカル経路）。"""
    monkeypatch.setattr(settings, "policy_store_uri", "")
