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


class FakeGcsBlob:
    """google-cloud-storage Blob の最小フェイク（reload/download/upload＋generation precondition）。"""

    def __init__(self, store: dict):
        self._store = store  # {"data": bytes|None, "generation": int}

    def reload(self):
        from google.api_core.exceptions import NotFound

        if self._store["data"] is None:
            raise NotFound("object not found")
        self.generation = self._store["generation"]

    def download_as_bytes(self) -> bytes:
        return self._store["data"]

    def upload_from_string(self, payload, content_type=None, if_generation_match=None):
        from google.api_core.exceptions import PreconditionFailed

        current = self._store["generation"] if self._store["data"] is not None else 0
        if if_generation_match is not None and if_generation_match != current:
            raise PreconditionFailed("generation mismatch")
        self._store["data"] = payload.encode("utf-8")
        self._store["generation"] = current + 1


@pytest.fixture()
def gcs_store(monkeypatch):
    """policy_store の外部ストアをフェイク GCS へ向ける（creds 不要・決定的）。"""
    from hoiku_agent.harness import policy_store as ps

    store = {"data": None, "generation": 0}
    monkeypatch.setattr(ps, "_gcs_blob", lambda uri: FakeGcsBlob(store))
    monkeypatch.setattr(settings, "policy_store_uri", "gs://bucket/文書作成指針.json")
    return store
