"""Web リクエストの検証済み identity から workspace 境界を解決する。"""

from __future__ import annotations

from datetime import datetime

from fastapi import Request

from ..harness import record_store
from . import auth


def resolve_workspace_id(request: Request, now: datetime) -> str | None:
    """認証済み Google subject の個人 workspace を返す。

    identity は署名付き session だけから読み、body・ツール引数・LLM 出力は使わない。認証を無効にした
    ローカル開発では None（各ストアの default 領域）へ降格する。
    """
    signed_in = auth.current_google_user(request)
    if not signed_in:
        return None
    user = record_store.touch_user(
        signed_in.email,
        google_subject=signed_in.subject,
        now=now,
    )
    return str(user.get("workspace_id") or "") or None
