"""雛形が壊れていないことだけ確認するスモークテスト。

ADK 等の依存が未インストールでも構造確認できるよう、import 失敗は skip 扱いにする。
依存導入後（uv sync）に root_agent の構築まで通ることを確認する。
"""

import pytest


def test_schemas_import():
    from hoiku_agent.schemas import AgeBand, DocumentSpec, DocumentType

    spec = DocumentSpec(doc_type=DocumentType.保育日誌, age_band=AgeBand.零から二歳)
    assert spec.doc_type == DocumentType.保育日誌
    assert spec.age_band is AgeBand.零から二歳


def test_root_agent_builds():
    adk = pytest.importorskip("google.adk", reason="google-adk 未インストール（uv sync 後に有効化）")
    assert adk is not None

    from hoiku_agent import root_agent

    assert root_agent.name == "document_pipeline"
