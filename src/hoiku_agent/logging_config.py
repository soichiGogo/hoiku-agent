"""構造化ログ設定（Cloud Run 向け・本番運用ブラッシュアップ）。

Google Cloud のログ推奨に沿い、**アプリは stdout に「1行 JSON（`severity`/`message` を持つ）」を吐くだけ**で、
Cloud Run のロギングエージェントがそれを Cloud Logging の構造化エントリへ自動昇格する
（`logging.googleapis.com/severity` でフィルタ・Error Reporting 起動・トレース相関が効く）。
**Cloud Logging クライアントは手組みしない**（マネージドの取り込みに委ねる＝§9 の「呼ぶだけ」哲学と同型）。

- 参照: https://cloud.google.com/run/docs/logging / https://cloud.google.com/logging/docs/structured-logging
- severity は Python の levelname をそのまま使う（DEBUG/INFO/WARNING/ERROR/CRITICAL は Cloud Logging の
  severity 文字列と一致）。
- トレース相関: Cloud Run が付ける `X-Cloud-Trace-Context` を middleware で拾い、`logging.googleapis.com/trace`
  に `projects/<PROJECT>/traces/<TRACE_ID>` を載せる（同一リクエストのログが Logs Explorer で束ねられる）。
- ローカル DX: `K_SERVICE`（Cloud Run が必ず注入）が無く `LOG_FORMAT` 未指定なら人が読めるテキスト整形に
  降格する（本番＝JSON・ローカル＝テキストを既定にしつつ `LOG_FORMAT=json|text` で明示上書き可）。
"""

from __future__ import annotations

import json
import logging
import os
import sys
from contextvars import ContextVar

# 現在処理中リクエストのトレースID（middleware が set・formatter が読む）。未設定は None。
_trace_id: ContextVar[str | None] = ContextVar("cloud_trace_id", default=None)


class _CloudLoggingJSONFormatter(logging.Formatter):
    """1行 JSON（Cloud Logging 構造化エントリ）へ整形する。"""

    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, object] = {
            "severity": record.levelname,  # DEBUG/INFO/WARNING/ERROR/CRITICAL＝Cloud Logging と一致
            "message": record.getMessage(),
            "logger": record.name,
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
        }
        trace = _trace_id.get()
        if trace:
            entry["logging.googleapis.com/trace"] = trace
        if record.exc_info:
            # 例外はスタックトレースを message へ畳み込む（Error Reporting が拾えるよう ERROR で1エントリに）。
            entry["message"] = f"{entry['message']}\n{self.formatException(record.exc_info)}"
        # 追加の構造化フィールド（logger.info(..., extra={"json_fields": {...}}) で渡せる）。
        extra = getattr(record, "json_fields", None)
        if isinstance(extra, dict):
            entry.update(extra)
        return json.dumps(entry, ensure_ascii=False, default=str)


def _use_json() -> bool:
    """JSON 整形にするか。明示 `LOG_FORMAT` 優先／既定は Cloud Run（`K_SERVICE` 有）で JSON。"""
    fmt = os.getenv("LOG_FORMAT", "").strip().lower()
    if fmt in ("json", "text"):
        return fmt == "json"
    return bool(os.getenv("K_SERVICE"))  # Cloud Run では必ず入る


def configure_logging() -> None:
    """ルートロガーへ stdout ハンドラを1つ据える（冪等）。アプリ入口から1回呼ぶ。"""
    root = logging.getLogger()
    level = os.getenv("LOG_LEVEL", "INFO").upper()
    root.setLevel(getattr(logging, level, logging.INFO))

    # 既存の自前ハンドラを外して二重出力を防ぐ（uvicorn 等が付けた既定ハンドラも掃除）。
    for h in list(root.handlers):
        root.removeHandler(h)

    handler = logging.StreamHandler(sys.stdout)
    if _use_json():
        handler.setFormatter(_CloudLoggingJSONFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s"))
    root.addHandler(handler)

    # uvicorn / gunicorn の子ロガーはルートに伝播させる（独自ハンドラを持たせない＝JSON へ揃える）。
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "gunicorn.error", "gunicorn.access"):
        lg = logging.getLogger(name)
        lg.handlers.clear()
        lg.propagate = True


def _parse_trace_header(header: str, project: str) -> str | None:
    """`X-Cloud-Trace-Context: TRACE_ID/SPAN_ID;o=1` → `projects/<project>/traces/<TRACE_ID>`。"""
    trace_id = header.split("/", 1)[0].strip()
    if not trace_id or not project:
        return None
    return f"projects/{project}/traces/{trace_id}"


def install_trace_middleware(app) -> None:
    """リクエストの `X-Cloud-Trace-Context` を contextvar に載せ、ログをトレースへ相関させる。

    プロジェクト未設定（ローカル）や ヘッダ無しなら何もしない（トレースフィールドを付けないだけ）。
    """
    from .config import settings

    @app.middleware("http")
    async def _bind_trace(request, call_next):
        project = settings.google_cloud_project.strip()
        header = request.headers.get("x-cloud-trace-context", "")
        token = None
        if header and project:
            trace = _parse_trace_header(header, project)
            if trace:
                token = _trace_id.set(trace)
        try:
            return await call_next(request)
        finally:
            if token is not None:
                _trace_id.reset(token)
