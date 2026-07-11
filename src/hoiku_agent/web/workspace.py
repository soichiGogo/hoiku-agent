"""Web リクエストの検証済み identity から workspace 境界を解決する。"""

from __future__ import annotations

import logging
from datetime import datetime

from fastapi import Request

from ..harness import demo_seed, record_store
from . import auth

logger = logging.getLogger(__name__)


def provision_user(email: str, google_subject: str, now: datetime) -> dict:
    """検証済み Google identity の users 行を auto-provision して返す（touch_user の web 共通口）。

    **新規に個人 workspace を作った呼び出し（初回ログイン）では、その場でデフォルト seed を投入**する
    （`demo_seed.seed_workspace`＝クラス・園児・確定書類チェーン＝初見でも全タブを体感できる状態）。
    トリガは `touch_user` の workspace_created（users の UNIQUE により高々1回）で、seed 自体も冪等。
    seed の失敗はログイン本流を壊さない（warning ログ＋続行。「データを初期化」で自己回復できる）。
    email/subject は呼び出し元が **Google の検証済み値**を渡す（body 由来を使わない）。
    """
    user = record_store.touch_user(email, google_subject=google_subject, now=now)
    if user.get("workspace_created"):
        workspace_id = str(user.get("workspace_id") or "") or None
        try:
            seeded = demo_seed.seed_workspace(workspace_id, now=now)
            logger.info("初回ログインのデフォルト seed: workspace=%s %s", workspace_id, seeded)
        except Exception:
            logger.warning(
                "初回ログインのデフォルト seed に失敗（続行）: workspace=%s",
                workspace_id,
                exc_info=True,
            )
    return user


def resolve_user(request: Request, now: datetime) -> dict | None:
    """認証済み Google subject の users 行を auto-provision して返す（未サインインは None）。

    identity は署名付き session だけから読み、body・ツール引数・LLM 出力は使わない。
    """
    signed_in = auth.current_google_user(request)
    if not signed_in:
        return None
    return provision_user(signed_in.email, signed_in.subject, now)


def resolve_workspace_id(request: Request, now: datetime) -> str | None:
    """認証済み Google subject の個人 workspace を返す。

    認証を無効にしたローカル開発では None（各ストアの default 領域）へ降格する。
    """
    user = resolve_user(request, now)
    if not user:
        return None
    return str(user.get("workspace_id") or "") or None
