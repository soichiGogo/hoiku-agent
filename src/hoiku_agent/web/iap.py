"""IAP for Cloud Run の検証済み identity 取得（Phase 3 認証・§11 配信）。

IAP を有効化した Cloud Run には、IAP がリクエストへ `x-goog-iap-jwt-assertion`（署名付き JWT）を
付けて渡す。ここでは **audience（`IAP_AUDIENCE`）を設定した場合のみ** JWT を IAP の公開鍵で
署名検証し、検証済みの Google アカウント email を返す。

守る線:
- **未設定は完全降格（fail-closed）**: `IAP_AUDIENCE` が空ならヘッダを一切信用せず None
  （IAP を経由しない面＝直アクセス可能な構成でのヘッダ偽装を防ぐ。actor は従来の自己申告のまま）。
- 検証失敗（期限切れ・偽署名・audience 不一致）も None＝匿名扱い（例外で本流を壊さない。
  パスコードゲート等の既存防御はそのまま重なる）。
- ここは「誰か」を確定するだけ。users への記録（auto-provision）は harness/record_store、
  actor の採用は routes（web は中継・決定的実体は harness＝§5 の流儀）。
"""

from __future__ import annotations

from fastapi import Request

from ..config import settings

# IAP の署名検証用公開鍵（ES256）。google-auth が取得・キャッシュする。
_IAP_CERTS_URL = "https://www.gstatic.com/iap/verify/public_key"
_HEADER = "x-goog-iap-jwt-assertion"


def _verify_assertion(assertion: str, audience: str) -> dict:
    """IAP JWT を署名検証して claims を返す（失敗は例外）。テストではここを差し替える。"""
    from google.auth.transport import requests as ga_requests
    from google.oauth2 import id_token

    return id_token.verify_token(
        assertion,
        ga_requests.Request(),
        audience=audience,
        certs_url=_IAP_CERTS_URL,
    )


def verified_iap_email(request: Request) -> str | None:
    """リクエストから検証済みの Google アカウント email を返す（未設定/未認証/検証失敗は None）。"""
    audience = settings.iap_audience.strip()
    if not audience:
        return None
    assertion = request.headers.get(_HEADER, "").strip()
    if not assertion:
        return None
    try:
        claims = _verify_assertion(assertion, audience)
    except Exception:  # noqa: BLE001  検証失敗＝匿名扱い（本流を壊さない・偽の認証を通さない）
        return None
    email = str(claims.get("email") or "").strip()
    # IAP は subject/email に "accounts.google.com:" プレフィックスを付ける形式もある＝剥がして正規化。
    return email.removeprefix("accounts.google.com:") or None
