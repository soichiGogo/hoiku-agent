"""保育士 Web UI の自前ルート＋簡易パスコードゲート（§11 配信）。

ここに置くのは「ADK ネイティブ REST では賄えない最小限」だけ：
- `GET /api/config`  … フロントが起動時に読む（app_name・既定ユーザ・接続状況・パスコード要否）。
- `GET /api/policy`  … 育つ指針（`knowledge/文書作成指針.md`）の現物。改善ダッシュボードの before 表示用。
- `POST /api/gate`   … 簡易パスコードの検証＋cookie 発行（配布リンクのコスト/濫用対策）。
- `POST /api/improve`… improver（二階）を SSE 駆動（実体は `improver_stream` ＝別エントリの原則を保つ）。

日誌/月案の生成自体はフロントが ADK の `/run_sse`・`/apps/{app}/...` を直接叩くため、ここには無い
（自前 Runner を組まない＝§9）。決定的ロジックも持たない（harness/eval が唯一実装＝§5）。
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ..config import settings

# このパッケージは src/hoiku_agent/web。repo root は3つ上（web→hoiku_agent→src→root）。
_WEB_DIR = Path(__file__).resolve().parent
_STATIC_DIR = _WEB_DIR / "static"
_REPO_ROOT = _WEB_DIR.parents[2]
_GUIDELINE_PATH = _REPO_ROOT / "knowledge" / "文書作成指針.md"

# ADK の app_name＝agents_dir(src) 配下のパッケージ名（GET /list-apps と一致）。
APP_NAME = "hoiku_agent"
DEFAULT_USER_ID = "caregiver"
_COOKIE_NAME = "hoiku_demo"

# LLM を回す（＝課金が発生する）口だけをパスコードで守る。読み取り・セッション作成は素通し。
_GATED_EXACT = {"/run", "/run_sse", "/run_live"}
_GATED_PREFIX = ("/api/improve",)


class GateRequest(BaseModel):
    passcode: str


def _is_authed(request: Request) -> bool:
    """パスコード未設定なら常に許可。設定時は cookie かヘッダで一致を要求する。"""
    pc = settings.demo_passcode
    if not pc:
        return True
    return request.cookies.get(_COOKIE_NAME) == pc or request.headers.get("x-demo-passcode") == pc


def _needs_gate(path: str) -> bool:
    return path in _GATED_EXACT or any(path.startswith(p) for p in _GATED_PREFIX)


def register_web_ui(app: FastAPI) -> FastAPI:
    """`get_fast_api_app` が返した app に保育士 UI を同居させる（server.py から1回呼ぶ）。"""

    @app.middleware("http")
    async def _passcode_guard(request: Request, call_next):
        # demo_passcode 設定時のみ・LLM を回す口だけをゲートする（静的UI・config・読み取りは素通し）。
        if settings.demo_passcode and _needs_gate(request.url.path) and not _is_authed(request):
            return JSONResponse(
                {"error": "パスコードが必要です", "code": "passcode_required"},
                status_code=401,
            )
        response = await call_next(request)
        # 配布 SPA の静的資産（/app/ 配下の ES モジュール等）は常に再検証させる。StaticFiles は
        # Cache-Control を付けないためブラウザがヒューリスティックに古い JS をキャッシュし、UI 更新が
        # 反映されず「壊れて見える」ことがある。no-cache（=毎回 conditional 再検証・更新時のみ 200）で防ぐ。
        if request.url.path == "/app" or request.url.path.startswith("/app/"):
            response.headers["Cache-Control"] = "no-cache"
        return response

    @app.get("/api/config")
    async def web_config() -> dict:
        """フロントの起動時設定。接続状況は env から導出（未接続は降格表示に使う）。"""
        return {
            "app_name": APP_NAME,
            "default_user_id": DEFAULT_USER_ID,
            "memory_connected": bool(settings.agent_engine_id),
            "rag_connected": bool(settings.rag_corpus),
            "passcode_required": bool(settings.demo_passcode),
            "model": settings.gemini_model,
        }

    @app.get("/api/policy")
    async def web_policy() -> dict:
        """育つ文書作成指針の現物（improver ダッシュボードの before 表示・§9）。"""
        if _GUIDELINE_PATH.exists():
            return {"markdown": _GUIDELINE_PATH.read_text(encoding="utf-8")}
        return {"markdown": "（文書作成指針は未整備）"}

    @app.get("/api/eval-baseline")
    async def web_eval_baseline():
        """committed `eval/baseline.json`（main の eval 基準）。改善ダッシュボードの常時表示用。

        コンテナでは eval/ が除外され得るため不在は許容（null 返し＝降格・偽の数字を出さない）。
        """
        path = _REPO_ROOT / "eval" / "baseline.json"
        if not path.exists():
            return JSONResponse(None)
        try:
            return JSONResponse(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            return JSONResponse(None)

    @app.post("/api/gate")
    async def web_gate(req: GateRequest):
        """簡易パスコード検証。一致で cookie を発行（共有1パスコード＝配布デモ用）。"""
        if not settings.demo_passcode:
            return {"ok": True, "required": False}
        if req.passcode == settings.demo_passcode:
            resp = JSONResponse({"ok": True})
            resp.set_cookie(
                _COOKIE_NAME,
                settings.demo_passcode,
                httponly=True,
                samesite="lax",
                max_age=86400,
            )
            return resp
        return JSONResponse({"ok": False, "error": "パスコードが違います"}, status_code=401)

    # improver（二階）を SSE 駆動する口。別モジュールに実体（別エントリの原則・§8）。
    from .improver_stream import register_improver_route

    register_improver_route(app)

    # 配布リンクの素の URL（/）を保育士 UI に着地させる。ADK 既定は / → /dev-ui へ飛ばすので、
    # その GET / 経路だけ差し替える（dev UI は /dev-ui/ に温存）。審査員がパスを打たずに済むように。
    app.router.routes = [
        r
        for r in app.router.routes
        if not (getattr(r, "path", None) == "/" and "GET" in (getattr(r, "methods", None) or set()))
    ]

    @app.get("/")
    async def _root_to_app():
        return RedirectResponse("/app/")

    @app.get("/app")
    async def _app_index_redirect():
        # StaticFiles マウントは末尾スラッシュ必須なので /app → /app/ に寄せる。
        return RedirectResponse("/app/")

    # 保育士 UI（自前 SPA）。html=True で /app/ が index.html を返す。static は src 配下＝Dockerfile 不変。
    app.mount("/app", StaticFiles(directory=str(_STATIC_DIR), html=True), name="hoiku-ui")

    return app
