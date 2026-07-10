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
from dataclasses import dataclass
from typing import Any

from fastapi import Request

from ..config import settings

_LOGIN_CSRF_SESSION_KEY = "google_login_csrf"
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


def issue_login_csrf(request: Request) -> str:
    """案内画面で一度だけ使える、同一オリジンの Google ログイン用 CSRF token を発行する。"""
    token = secrets.token_urlsafe(32)
    request.session[_LOGIN_CSRF_SESSION_KEY] = token
    return token


def login_csrf_matches(request: Request, token: str) -> bool:
    """popup callback の同一オリジン POST が案内画面から始まったことを確認する。"""
    expected = request.session.get(_LOGIN_CSRF_SESSION_KEY)
    return isinstance(expected, str) and bool(token) and hmac.compare_digest(expected, token)


def consume_login_csrf(request: Request) -> None:
    """ログイン成功後に CSRF token を使い捨てにする。"""
    request.session.pop(_LOGIN_CSRF_SESSION_KEY, None)


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
