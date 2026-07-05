"""構造化ログ設定の決定論テスト（LLM/GCP 非依存・本番運用ブラッシュアップ）。

Cloud Run へ吐く1行 JSON が severity/message を持ち、例外・トレース相関・追加フィールドを
正しく載せることを検査する（Logs Explorer のフィルタ／Error Reporting 起動の前提）。
"""

from __future__ import annotations

import json
import logging

from hoiku_agent import logging_config as lc


def _record(level: int = logging.INFO, msg: str = "hello", **kw) -> logging.LogRecord:
    return logging.LogRecord("hoiku.test", level, __file__, 1, msg, kw or None, None)


def test_json_formatter_has_severity_and_message():
    out = json.loads(lc._CloudLoggingJSONFormatter().format(_record(logging.WARNING, "危険")))
    assert out["severity"] == "WARNING"  # Cloud Logging の severity 文字列と一致
    assert out["message"] == "危険"
    assert out["logger"] == "hoiku.test"


def test_json_formatter_folds_exception_into_message():
    import sys

    try:
        raise ValueError("boom")
    except ValueError:
        rec = logging.LogRecord(
            "hoiku.test", logging.ERROR, __file__, 1, "落ちた", None, sys.exc_info()
        )
    out = json.loads(lc._CloudLoggingJSONFormatter().format(rec))
    assert out["severity"] == "ERROR"
    assert "落ちた" in out["message"] and "ValueError" in out["message"]


def test_json_formatter_includes_trace_when_bound():
    token = lc._trace_id.set("projects/p/traces/abc123")
    try:
        out = json.loads(lc._CloudLoggingJSONFormatter().format(_record()))
    finally:
        lc._trace_id.reset(token)
    assert out["logging.googleapis.com/trace"] == "projects/p/traces/abc123"


def test_json_formatter_merges_json_fields_extra():
    rec = _record()
    rec.json_fields = {"child_id": "はるとくん", "doc_type": "diary"}
    out = json.loads(lc._CloudLoggingJSONFormatter().format(rec))
    assert out["child_id"] == "はるとくん" and out["doc_type"] == "diary"


def test_parse_trace_header():
    assert (
        lc._parse_trace_header("TRACE123/456;o=1", "my-proj") == "projects/my-proj/traces/TRACE123"
    )
    assert lc._parse_trace_header("TRACE123/456", "") is None  # project 未設定は付けない
    assert lc._parse_trace_header("", "my-proj") is None


def test_use_json_respects_explicit_and_cloud_run(monkeypatch):
    monkeypatch.setenv("LOG_FORMAT", "json")
    assert lc._use_json() is True
    monkeypatch.setenv("LOG_FORMAT", "text")
    assert lc._use_json() is False
    monkeypatch.delenv("LOG_FORMAT", raising=False)
    monkeypatch.delenv("K_SERVICE", raising=False)
    assert lc._use_json() is False  # ローカル既定＝テキスト
    monkeypatch.setenv("K_SERVICE", "hoiku-agent")
    assert lc._use_json() is True  # Cloud Run 既定＝JSON


def test_configure_logging_installs_single_stdout_handler(monkeypatch):
    root = logging.getLogger()
    saved_handlers, saved_level = list(root.handlers), root.level
    monkeypatch.setenv("LOG_FORMAT", "json")
    try:
        lc.configure_logging()
        lc.configure_logging()  # 冪等：二重呼びでもハンドラは増えない
        stream_handlers = [h for h in root.handlers if isinstance(h, logging.StreamHandler)]
        assert len(stream_handlers) == 1
        assert isinstance(stream_handlers[0].formatter, lc._CloudLoggingJSONFormatter)
    finally:
        # グローバルなルートロガーを元に戻す（pytest のログ捕捉や後続テストへ漏らさない）。
        for h in list(root.handlers):
            root.removeHandler(h)
        for h in saved_handlers:
            root.addHandler(h)
        root.setLevel(saved_level)
