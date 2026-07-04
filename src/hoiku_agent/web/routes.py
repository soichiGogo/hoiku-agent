"""保育士 Web UI の自前ルート＋簡易パスコードゲート（§11 配信）。

ここに置くのは「ADK ネイティブ REST では賄えない最小限」だけ：
- `GET /api/config`  … フロントが起動時に読む（app_name・既定ユーザ・接続状況・パスコード要否）。
- `GET /api/policy`  … 育つ指針＝構造化カード＋変更履歴（「指針を育てる」タブの閲覧・§8/§9）。
- `POST /api/gate`   … 簡易パスコードの検証＋cookie 発行（配布リンクのコスト/濫用対策）。
- `POST /api/improve`… improver（二階）を SSE 駆動（実体は `improver_stream` ＝別エントリの原則を保つ）。
- `/api/records`・`/api/children` … 書類アーカイブ（確定書類・承認証跡・児童マスタ＝harness/record_store
  の中継・Phase 1）。now の解決だけが runtime 境界（決定的実体は harness に1つ・LLM 非課金で非ゲート）。

日誌/月案の生成自体はフロントが ADK の `/run_sse`・`/apps/{app}/...` を直接叩くため、ここには無い
（自前 Runner を組まない＝§9）。決定的ロジックも持たない（harness/eval が唯一実装＝§5）。
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ..config import settings
from ..harness import policy_store, record_store
from ..harness.finalize import finalize_entry
from ..schemas import FiveDomains, TenNoSugata, ThreeViewpoint
from .chohyo_pdf import render_pdf

# このパッケージは src/hoiku_agent/web。repo root は3つ上（web→hoiku_agent→src→root）。
_WEB_DIR = Path(__file__).resolve().parent
_STATIC_DIR = _WEB_DIR / "static"
_REPO_ROOT = _WEB_DIR.parents[2]

# ADK の app_name＝agents_dir(src) 配下のパッケージ名（GET /list-apps と一致）。
APP_NAME = "hoiku_agent"
DEFAULT_USER_ID = "caregiver"
_COOKIE_NAME = "hoiku_demo"

# LLM を回す（＝課金が発生する）口だけをパスコードで守る。読み取り・セッション作成は素通し。
_GATED_EXACT = {"/run", "/run_sse", "/run_live"}
_GATED_PREFIX = ("/api/improve",)


class GateRequest(BaseModel):
    passcode: str


class FinalizeEditRequest(BaseModel):
    """保育士の編集フォームから来る再確定リクエスト（編集UI・§11 presentation）。

    生成・採点ロジックは持たず、harness の finalize_entry を中継するだけ（決定的実体は harness に1つ＝§5）。
    """

    kind: str = "diary"  # "diary" / "monthly" / "child_record"
    entry: dict  # 編集後の DiaryEntry / MonthlyPlan / ChildRecord 相当の dict
    doc_date: str | None = None  # 記録日（日誌・ISO 文字列。機械メタなので harness が上書き）


class ExportPdfRequest(BaseModel):
    """帳票PDF 出力リクエスト（現場でそのまま綴じる最終形・§11/§18 presentation）。

    現在の（編集後の）確定 entry を園の様式に近い帳票PDFへ描くだけ。描画は web/chohyo_pdf に1つ、
    型検査はしない（型の保証は harness の責務＝§5）。LLM 非課金なのでパスコード非ゲート。
    """

    kind: str = "diary"  # "diary" / "monthly" / "child_record"
    entry: dict  # 帳票に描く DiaryEntry / MonthlyPlan / ChildRecord 相当の dict


class RecordSaveRequest(BaseModel):
    """確定書類のアーカイブ保存（AI 確定時と保育士の編集保存時にフロントが呼ぶ・Phase 1）。

    永続化の決定的実体は harness/record_store（ここは now を注入して中継するだけ）。
    actor は担当者の自己申告（認証は Phase 3=IAP で users と突合）。
    """

    kind: str = "diary"
    entry: dict
    rendered_text: str = ""  # write_draft の整形テキスト（state["final_document"]）
    author_kind: str = "ai"  # "ai"（AI 確定）/ "caregiver"（保育士の編集保存）
    actor: str = ""


class RecordApproveRequest(BaseModel):
    """書類の承認記録（承認証跡＝audit_events。ADK state の caregiver_approved と並走）。"""

    kind: str = "diary"
    entry: dict
    actor: str = ""


def _pdf_filename(kind: str, entry: dict) -> str:
    """帳票PDF のダウンロード名（日本語。RFC5987 で Content-Disposition に載せる）。"""
    if kind == "monthly":
        stem = f"月案_{entry.get('month') or ''}_{entry.get('child_id') or ''}".rstrip("_")
    elif kind == "child_record":
        stem = f"児童票_{entry.get('period') or ''}_{entry.get('child_id') or ''}".rstrip("_")
    else:
        stem = f"保育日誌_{entry.get('date') or ''}".rstrip("_")
    return f"{stem or '書類'}.pdf"


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
            "records_connected": bool(settings.database_url),
            "passcode_required": bool(settings.demo_passcode),
            "model": settings.gemini_model,
        }

    @app.get("/api/policy")
    async def web_policy() -> dict:
        """育つ文書作成指針＝構造化カード＋変更履歴（「指針を育てる」タブの閲覧・§8/§9）。

        ストア未配線/壊れは {cards:[], history:[], store:"unavailable"} で降格（偽の中身を出さない）。
        store は永続性を正直に示す（persistent / ephemeral=Cloud Run 揮発 / unavailable）。
        """
        try:
            view = policy_store.book_view(policy_store.load_book())
            view["store"] = policy_store.store_status()
            return view
        except Exception:  # noqa: BLE001  未配線/壊れは閲覧降格（偽の中身を出さない）
            return {"cards": [], "history": [], "store": "unavailable"}

    @app.get("/api/form-meta")
    async def web_form_meta() -> dict:
        """編集フォームのタグ選択肢（年齢枠組みの語彙）。schemas の Enum が SSOT（JS で二重定義しない）。"""
        return {
            "three_viewpoint": [e.value for e in ThreeViewpoint],
            "five_domains": [e.value for e in FiveDomains],
            "ten_no_sugata": [e.value for e in TenNoSugata],
        }

    @app.post("/api/finalize-edit")
    async def web_finalize_edit(req: FinalizeEditRequest) -> dict:
        """保育士が編集した書類エントリを harness で**再検査・再整形**する（編集UIの保存・§5/§11）。

        決定的ロジックは持ち込まず harness の finalize_entry を中継するだけ。state は書かず（フロントが
        ADK の PATCH で final_entry/final_document/validation を更新する）、結果だけ返す。LLM 非課金なので
        パスコード非ゲート。
        """
        doc_date: date | None = None
        if req.doc_date:
            try:
                doc_date = date.fromisoformat(req.doc_date)
            except ValueError:
                doc_date = None
        result = finalize_entry(req.entry, kind=req.kind, doc_date=doc_date)
        return {
            "formatted": result.formatted,
            "problems": result.problems,
            "parse_error": result.parse_error,
            "ok": result.ok,
        }

    @app.post("/api/export-pdf")
    async def web_export_pdf(req: ExportPdfRequest):
        """確定 entry を園の帳票PDFに描いて返す（現場でそのまま綴じる最終形・§11/§18）。

        描画のみ（型の保証は harness）。kind/entry 不正は 400（握りつぶさず可視化）。LLM 非課金で非ゲート。
        """
        try:
            pdf = render_pdf(req.kind, req.entry)
        except ValueError as e:
            return JSONResponse({"error": str(e), "code": "invalid_request"}, status_code=400)
        filename = _pdf_filename(req.kind, req.entry)
        # ASCII フォールバック＋RFC5987（UTF-8）で日本語ファイル名を両載せする。
        disposition = f"attachment; filename=\"document.pdf\"; filename*=UTF-8''{quote(filename)}"
        return Response(
            content=pdf,
            media_type="application/pdf",
            headers={"Content-Disposition": disposition},
        )

    # ── 書類アーカイブ（harness/record_store の中継・Phase 1）───────────────────────────
    # sync def＝FastAPI が threadpool で回す（同期 DB I/O でイベントループを塞がない）。
    # now の注入だけが runtime 境界（record_store は clock を持たない＝§5 の流儀）。

    @app.post("/api/records")
    def web_save_record(req: RecordSaveRequest) -> dict:
        """確定書類をアーカイブへ保存（AI 確定＝finalize / 保育士編集＝edit の版を積む）。"""
        return record_store.save_document(
            req.kind,
            req.entry,
            req.rendered_text,
            author_kind=req.author_kind,
            actor=req.actor,
            now=datetime.now(),
        )

    @app.post("/api/records/approve")
    def web_approve_record(req: RecordApproveRequest) -> dict:
        """書類を承認済みにし証跡を残す（誰が承認したか＝actor 自己申告）。"""
        return record_store.approve_document(
            req.kind, req.entry, actor=req.actor, now=datetime.now()
        )

    @app.get("/api/records")
    def web_list_records(
        doc_type: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> dict:
        """アーカイブの書類一覧（メタ）。未設定/障害は空（偽の中身を出さない）。"""

        def _parse(raw: str | None) -> date | None:
            try:
                return date.fromisoformat(raw) if raw else None
            except ValueError:
                return None

        return {
            "documents": record_store.list_documents(
                doc_type=doc_type, date_from=_parse(date_from), date_to=_parse(date_to)
            ),
            "store": record_store.store_status(),
        }

    @app.get("/api/records/diary-entries")
    def web_list_diary_entries(date_from: str, date_to: str) -> dict:
        """期間内の日誌 entry（最新版 JSON）＝月案 L2／児童票 L3 の seed 取得口。

        フロントは entries が空/未接続なら従来のサンプル seed へ降格する（黙って空 seed で回さない）。
        """
        try:
            f, t = date.fromisoformat(date_from), date.fromisoformat(date_to)
        except ValueError:
            return JSONResponse(
                {"error": "date_from/date_to は YYYY-MM-DD", "code": "invalid_request"},
                status_code=400,
            )
        return {
            "entries": record_store.list_diary_entries(f, t),
            "store": record_store.store_status(),
        }

    @app.get("/api/children")
    def web_list_children() -> dict:
        """児童マスタ（アーカイブから auto-create された子）。未設定は空＝フロントは従来チップへ降格。"""
        return {"children": record_store.list_children(), "store": record_store.store_status()}

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
