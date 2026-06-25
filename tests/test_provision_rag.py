"""provision_rag_corpus の GCP 非依存な純ロジックのテスト（取り込み対象収集・一過性エラー判定）。

運用スクリプトだが、_collect_docs（対象拡張子フィルタ・空/欠如で SystemExit）と
_is_transient_create_error（serverless 切替/API 有効化の伝播待ちだけリトライ判定）は creds 不要で回せる
純ロジックで、誤分類すると「致命的エラーを延々リトライ」「一過性を即死」に静かに転びうるため固定する。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

pytest.importorskip("vertexai", reason="vertexai 未インストール")


def _load_module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "provision_rag_corpus.py"
    spec = importlib.util.spec_from_file_location("provision_rag_corpus", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


prc = _load_module()


def test_collect_docs_filters_supported_suffixes(tmp_path):
    (tmp_path / "a.pdf").write_text("x", encoding="utf-8")
    (tmp_path / "b.txt").write_text("x", encoding="utf-8")
    (tmp_path / "skip.png").write_bytes(b"x")
    (tmp_path / ".gitkeep").write_text("", encoding="utf-8")
    names = {p.name for p in prc._collect_docs(tmp_path)}
    assert names == {"a.pdf", "b.txt"}


def test_collect_docs_empty_dir_exits(tmp_path):
    with pytest.raises(SystemExit):
        prc._collect_docs(tmp_path)  # 対象拡張子のファイルが無い


def test_collect_docs_missing_dir_exits(tmp_path):
    with pytest.raises(SystemExit):
        prc._collect_docs(tmp_path / "does-not-exist")


def test_is_transient_create_error_true_for_propagation():
    assert prc._is_transient_create_error(RuntimeError("... using Spanner mode ... restricted ..."))
    assert prc._is_transient_create_error(
        Exception("Vector Search API has not been used in project")
    )


def test_is_transient_create_error_false_for_real_failures():
    assert not prc._is_transient_create_error(ValueError("some unrelated failure"))
    assert not prc._is_transient_create_error(RuntimeError("quota exceeded"))
