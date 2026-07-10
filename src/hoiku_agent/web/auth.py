"""Google Sign-In の検証済みセッション（Web 認証・§11 配信）。

Cloud Run IAP はサービス到達前に Google の認証画面へ転送するため、案内画面から明示的に
ログインを始める UX とは両立しない。このモジュールは Google Identity Services が POST する
ID token をサーバ側で検証し、署名付きの同一オリジン session に最小限の identity を保持する。

認証の真実は Google の `sub`（不変の subject）で、email は表示・監査用の検証済み属性として
扱う。リクエストヘッダやフロントの body から identity を受け取らない。
"""

from __future__ import annotations

import hmac
import secrets
from hashlib import sha256
from dataclasses import dataclass
from typing import Any

from fastapi import Request

from ..config import settings

LOGIN_CSRF_COOKIE = "google_login_csrf"
_SESSION_USER = "google_user"


@dataclass(frozen=True)
class GoogleUser:
    """Google が検証済みとして返した、アプリが必要とする最小限の identity。"""

    subject: str
    email: str
    name: str = ""


def validate_google_credential(credential: str) -> GoogleUser:
    """Google Identity Services の ID token を署名・audience・期限まで検証する。

    `google-auth` が Google の公開鍵と issuer/audience を検証する。email_verified と subject は
    アプリ固有に明示して確認し、検証済みでない email や空 subject を session に載せない。
    テストではこの関数を差し替えて OAuth 通信なしにフローを確認する。
    """
    if not settings.google_oauth_client_id:
        raise ValueError("Google ログインの設定が不足しています")
    from google.auth.transport import requests as google_requests
    from google.oauth2 import id_token

    claims: dict[str, Any] = id_token.verify_oauth2_token(
        credential,
        google_requests.Request(),
        settings.google_oauth_client_id,
    )
    subject = str(claims.get("sub") or "").strip()
    email = str(claims.get("email") or "").strip().lower()
    if not subject or not email or claims.get("email_verified") is not True:
        raise ValueError("確認済みの Google アカウント情報を取得できませんでした")
    return GoogleUser(subject=subject, email=email, name=str(claims.get("name") or "").strip())


def issue_login_csrf() -> str:
    """案内画面で一度だけ使える Google ログイン用 CSRF token を発行する。"""
    return secrets.token_urlsafe(32)


def login_csrf_cookie_value(token: str) -> str:
    """CSRF token にサーバ署名を付け、cookie 注入では偽造できない値にする。"""
    signature = hmac.new(settings.session_secret.encode(), token.encode(), sha256).hexdigest()
    return f"{token}.{signature}"


def login_csrf_matches(request: Request, token: str) -> bool:
    """popup callback の header とサーバ署名済み HttpOnly cookie を照合する。"""
    expected = request.cookies.get(LOGIN_CSRF_COOKIE)
    if not isinstance(expected, str) or not token or not settings.session_secret:
        return False
    return hmac.compare_digest(expected, login_csrf_cookie_value(token))


def current_google_user(request: Request) -> GoogleUser | None:
    """署名付き session の Google identity を返す。不正・旧形式は匿名として扱う。"""
    raw = request.session.get(_SESSION_USER)
    if not isinstance(raw, dict):
        return None
    subject = str(raw.get("sub") or "").strip()
    email = str(raw.get("email") or "").strip().lower()
    if not subject or not email:
        return None
    return GoogleUser(subject=subject, email=email, name=str(raw.get("name") or "").strip())


def sign_in(request: Request, user: GoogleUser) -> None:
    """検証済み identity のみを署名付き session に保存する。ID token 自体は保存しない。"""
    request.session[_SESSION_USER] = {"sub": user.subject, "email": user.email, "name": user.name}


def sign_out(request: Request) -> None:
    """この端末のアプリセッションを破棄する（Google アカウント本体はログアウトしない）。"""
    request.session.pop(_SESSION_USER, None)
