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
    adk = pytest.importorskip(
        "google.adk", reason="google-adk 未インストール（uv sync 後に有効化）"
    )
    assert adk is not None

    from hoiku_agent import root_agent

    # root_agent は doc_type 分岐ルータ（既定＝保育日誌）。子に日誌・月案・児童票のパイプラインを持つ。
    assert root_agent.name == "hoiku_root"
    sub_names = {a.name for a in root_agent.sub_agents}
    assert sub_names == {"document_pipeline", "monthly_plan_pipeline", "child_record_pipeline"}


def test_memory_service_uri_from_config():
    """agent_engine_id → agentengine://<id>（未設定なら None＝InMemory 降格）。"""
    from hoiku_agent.config import Settings

    assert Settings(agent_engine_id="").memory_service_uri is None
    assert (
        Settings(agent_engine_id="proj/loc/123").memory_service_uri == "agentengine://proj/loc/123"
    )


def test_server_app_builds():
    """本番/ローカル共通の入口 server.py が FastAPI app を公開する（memory 未設定→InMemory 降格）。"""
    pytest.importorskip("google.adk", reason="google-adk 未インストール（uv sync 後に有効化）")

    import server

    # get_fast_api_app の戻り（FastAPI）。型名で確認（fastapi 依存を直接 import しない）。
    assert type(server.app).__name__ == "FastAPI"
