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

from functools import lru_cache

from fastapi import Request

from ..config import settings

# IAP の署名検証用公開鍵（ES256）。gstatic から取得する。
_IAP_CERTS_URL = "https://www.gstatic.com/iap/verify/public_key"
_HEADER = "x-goog-iap-jwt-assertion"


@lru_cache(maxsize=1)
def _request_transport():
    """公開鍵取得用の transport を1つだけ作って使い回す。

    `google.oauth2.id_token.verify_token` は呼び出しごとに certs_url を fetch し、キャッシュは
    cachecontrol 対応 Session を渡したときだけ効く。素の Request() を毎回作ると全リクエスト（/api/config
    は全ページロードで走る）で gstatic への同期 HTTPS 往復が発生する。モジュール寿命で1つ保持し、
    可能なら cachecontrol でキャッシュする（依存が無ければ素の Request にフォールバック）。
    """
    from google.auth.transport import requests as ga_requests

    try:
        import cachecontrol  # type: ignore[import-not-found]
        import requests as _requests

        return ga_requests.Request(session=cachecontrol.CacheControl(_requests.Session()))
    except Exception:  # noqa: BLE001  cachecontrol 不在等はキャッシュなしにフォールバック
        return ga_requests.Request()


def _verify_assertion(assertion: str, audience: str) -> dict:
    """IAP JWT を署名検証して claims を返す（失敗は例外）。テストではここを差し替える。"""
    from google.oauth2 import id_token

    return id_token.verify_token(
        assertion,
        _request_transport(),
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
