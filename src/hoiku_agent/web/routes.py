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

from fastapi import FastAPI, File, Form, Request, Response, UploadFile
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ..config import settings
from ..harness import notation_store, policy_store, record_store, template_store
from ..harness.finalize import finalize_entry
from ..harness.pipeline import MAX_REVIEW_ITERATIONS
from ..schemas import FiveDomains, NotationKind, NotationRule, TenNoSugata, ThreeViewpoint
from .chohyo_pdf import render_pdf
from .docx_fill import fill_docx
from .docx_fill import supported_kinds as docx_supported_kinds
from .iap import verified_iap_email
from .upload_parse import parse_uploaded_file

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
# /api/improve（改善エージェント）／/api/parse-upload（アップロード取込＝ファイル解析に LLM を回す）。
_GATED_PREFIX = ("/api/improve", "/api/parse-upload")
# 書類アーカイブ・表記ルールの「書込」も守る（公開デモ URL からの DB へのゴミデータ・偽承認証跡・
# 辞書荒らしの防止＝濫用対策の同枠）。読み取り（GET）は従来どおり素通し（コスト・改変リスクなし）。
_GATED_WRITE_PREFIX = ("/api/records", "/api/notation", "/api/children")


class GateRequest(BaseModel):
    passcode: str


class NotationAddRequest(BaseModel):
    """表記ルールの追加（保育士が育てる編集辞書・§5 ひらがな表記DX）。now は route 境界で注入。"""

    pattern: str  # 変換元（例: 子供）
    replacement: str = ""  # 変換先（例: 子ども）
    kind: str = "ひらがな化"  # NotationKind の値
    note: str = ""  # なぜこの表記か


class NotationUpdateRequest(BaseModel):
    """表記ルールの編集（None は据え置き。enabled で暴発ルールを止められる＝§5）。"""

    pattern: str | None = None
    replacement: str | None = None
    kind: str | None = None
    note: str | None = None
    enabled: bool | None = None


class FinalizeEditRequest(BaseModel):
    """保育士の編集フォームから来る再確定リクエスト（編集UI・§11 presentation）。

    生成・採点ロジックは持たず、harness の finalize_entry を中継するだけ（決定的実体は harness に1つ＝§5）。
    """

    kind: str = "diary"  # "diary" / "monthly" / "child_record" / "nursery_record"
    entry: dict  # 編集後の DiaryEntry / MonthlyPlan / ChildRecord / NurseryRecord 相当の dict
    doc_date: str | None = None  # 記録日（日誌・ISO 文字列。機械メタなので harness が上書き）


class ExportPdfRequest(BaseModel):
    """帳票PDF 出力リクエスト（現場でそのまま綴じる最終形・§11/§18 presentation）。

    現在の（編集後の）確定 entry を園の様式に近い帳票PDFへ描くだけ。描画は web/chohyo_pdf に1つ、
    型検査はしない（型の保証は harness の責務＝§5）。LLM 非課金なのでパスコード非ゲート。
    """

    kind: str = "diary"  # "diary" / "monthly" / "child_record" / "nursery_record"
    entry: dict  # 帳票に描く DiaryEntry / MonthlyPlan / ChildRecord / NurseryRecord 相当の dict


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


class ChildAddRequest(BaseModel):
    """新規児の登録（「書類を作る」で未登録名を選んだとき）。本名（姓/名）＋性別を受け取り、
    呼び名（名）＋敬称（性別導出）＝display_name を harness が合成して児童マスタへ upsert する。

    本名（姓名）は氏名欄用で **DB のみ・repo/eval には持ち込まない**（§14）。given_name は必須
    （呼び名＝表示名の素）、family_name は任意（氏名欄）。gender は male/female。"""

    given_name: str  # 名（＝呼び名・必須）
    family_name: str = ""  # 姓（氏名欄用・任意）
    gender: str = ""  # male / female（敬称導出・空は敬称なし）
    actor: str = ""


def _doc_filename(kind: str, entry: dict, ext: str) -> str:
    """書類のダウンロード名（日本語。RFC5987 で Content-Disposition に載せる）。ext は "pdf"/"docx"。"""
    if kind == "monthly":
        stem = f"月案_{entry.get('month') or ''}_{entry.get('child_id') or ''}".rstrip("_")
    elif kind == "child_record":
        stem = f"保育経過記録_{entry.get('period') or ''}_{entry.get('child_id') or ''}".rstrip("_")
    elif kind == "nursery_record":
        stem = f"保育要録_{entry.get('fiscal_year') or ''}_{entry.get('child_id') or ''}".rstrip(
            "_"
        )
    else:
        stem = f"保育日誌_{entry.get('date') or ''}".rstrip("_")
    return f"{stem or '書類'}.{ext}"


def _is_authed(request: Request) -> bool:
    """パスコード未設定なら常に許可。設定時は cookie かヘッダで一致を要求する。"""
    pc = settings.demo_passcode
    if not pc:
        return True
    return request.cookies.get(_COOKIE_NAME) == pc or request.headers.get("x-demo-passcode") == pc


def _needs_gate(path: str, method: str = "GET") -> bool:
    if path in _GATED_EXACT or any(path.startswith(p) for p in _GATED_PREFIX):
        return True
    # アーカイブは書込（POST 等）のみゲート（GET＝一覧/児童/seed は素通し）。
    return method != "GET" and any(path.startswith(p) for p in _GATED_WRITE_PREFIX)


def register_web_ui(app: FastAPI) -> FastAPI:
    """`get_fast_api_app` が返した app に保育士 UI を同居させる（server.py から1回呼ぶ）。"""

    @app.middleware("http")
    async def _passcode_guard(request: Request, call_next):
        # demo_passcode 設定時のみ・LLM を回す口だけをゲートする（静的UI・config・読み取りは素通し）。
        if (
            settings.demo_passcode
            and _needs_gate(request.url.path, request.method)
            and not _is_authed(request)
        ):
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
    async def web_config(request: Request) -> dict:
        """フロントの起動時設定。接続状況は env から導出（未接続は降格表示に使う）。

        user_email は IAP（Phase 3）の検証済み identity（IAP 未配線/未認証は None＝従来表示）。
        """
        return {
            "app_name": APP_NAME,
            "default_user_id": DEFAULT_USER_ID,
            "memory_connected": bool(settings.agent_engine_id),
            "rag_connected": bool(settings.rag_corpus),
            "records_connected": bool(settings.database_url),
            "passcode_required": bool(settings.demo_passcode),
            "model": settings.gemini_model,
            "user_email": verified_iap_email(request),
            # 園の実 Word 様式（.docx）流し込みに対応済みの kind＝UI が Word ダウンロードの出し分けに使う。
            "docx_kinds": docx_supported_kinds(),
            # レビュー巡回の上限（harness の SSOT）。UI は差し戻し時に「N巡目/最大M」を出す際の M に使う
            # （フロントで magic number を持たずドリフトを防ぐ＝harness/pipeline が正）。
            "max_review_iterations": MAX_REVIEW_ITERATIONS,
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

    # ── 表記ルール辞書（ひらがな表記DX＝harness/notation_store の中継・§5）─────────────────
    # 決定的実体は harness に1つ（CRUD＋正規化）。ここは now 注入＋楽観ロックの read-modify-write を
    # 中継するだけ。LLM 非課金だが書込は公開デモの辞書荒らし防止でパスコードゲート（読取は素通し）。
    _NOTATION_KINDS = {k.value: k for k in NotationKind}

    def _notation_view() -> dict:
        view = notation_store.book_view(notation_store.load_book())
        view["store"] = notation_store.store_status()
        return view

    def _commit_notation(mutate):
        """load→mutate(book)→save（version 楽観ロック）。ValueError は呼び出し側が 409 に変換。"""
        book, version = notation_store.load_book_meta()
        notation_store.save_book(mutate(book), if_version=version)

    @app.get("/api/notation")
    def web_notation() -> dict:
        """表記ルール一覧＋ストア永続性（未配線/壊れは空＋unavailable に降格＝偽の中身を出さない）。"""
        try:
            return _notation_view()
        except Exception:  # noqa: BLE001
            return {"rules": [], "store": "unavailable"}

    @app.post("/api/notation")
    def web_notation_add(req: NotationAddRequest):
        """表記ルールを追加する（保育士の追加。空/重複は 409 で正直に返す）。"""
        kind = _NOTATION_KINDS.get((req.kind or "").strip())
        if kind is None:
            return JSONResponse(
                {"status": "error", "detail": f"種別が不正です: {req.kind!r}"}, status_code=400
            )
        now = datetime.now()

        def _mutate(book):
            rule = NotationRule(
                id=notation_store.next_rule_id(book),
                pattern=req.pattern.strip(),
                replacement=req.replacement,
                kind=kind,
                note=req.note,
                source="保育士の追加",
                created_at=now,
                updated_at=now,
            )
            return notation_store.add_rule(book, rule)

        try:
            _commit_notation(_mutate)
        except ValueError as e:
            return JSONResponse({"status": "rejected", "detail": str(e)}, status_code=409)
        return {"status": "ok", **_notation_view()}

    @app.patch("/api/notation/{rule_id}")
    def web_notation_update(rule_id: str, req: NotationUpdateRequest):
        """表記ルールを編集する（pattern/replacement/種別/理由/有効の変更・None は据え置き）。"""
        kind = None
        if req.kind is not None:
            kind = _NOTATION_KINDS.get(req.kind.strip())
            if kind is None:
                return JSONResponse(
                    {"status": "error", "detail": f"種別が不正です: {req.kind!r}"}, status_code=400
                )
        now = datetime.now()
        try:
            _commit_notation(
                lambda book: notation_store.update_rule(
                    book,
                    rule_id=rule_id,
                    when=now,
                    pattern=req.pattern,
                    replacement=req.replacement,
                    kind=kind,
                    note=req.note,
                    enabled=req.enabled,
                )
            )
        except ValueError as e:
            return JSONResponse({"status": "rejected", "detail": str(e)}, status_code=409)
        return {"status": "ok", **_notation_view()}

    @app.delete("/api/notation/{rule_id}")
    def web_notation_delete(rule_id: str):
        """表記ルールを削除する（対象不在/競合は 409）。"""
        try:
            _commit_notation(lambda book: notation_store.remove_rule(book, rule_id=rule_id))
        except ValueError as e:
            return JSONResponse({"status": "rejected", "detail": str(e)}, status_code=409)
        return {"status": "ok", **_notation_view()}

    @app.get("/api/form-meta")
    async def web_form_meta() -> dict:
        """編集フォームのタグ選択肢（年齢枠組みの語彙）。schemas の Enum が SSOT（JS で二重定義しない）。"""
        return {
            "three_viewpoint": [e.value for e in ThreeViewpoint],
            "five_domains": [e.value for e in FiveDomains],
            "ten_no_sugata": [e.value for e in TenNoSugata],
        }

    @app.get("/api/doc-template")
    async def web_doc_template() -> dict:
        """様式テンプレート（本文セクションの順序・ラベル・種別）。編集フォームが本文の並び/見出しに使う。

        レイアウトのデータの SSOT は harness/template_store（テキスト整形・帳票PDF と共通）。JS は kind/key で
        widget を選び、順序と label をここから取る＝レイアウトの二重管理を解消（§18・§5）。読取なので非ゲート。
        取得失敗（未整備等）でもフロントは既定順にフォールバックできるよう、壊れても 200＋空で返す。
        """
        try:
            return template_store.book_view(template_store.load_book())
        except Exception:  # noqa: BLE001  壊れ/未整備はフロントのフォールバックに委ねる（空で 200）
            return {"templates": {}}

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
    def web_export_pdf(req: ExportPdfRequest):
        """確定 entry を園の帳票PDFに描いて返す（現場でそのまま綴じる最終形・§11/§18）。

        sync def＝FastAPI が threadpool で回す（アーカイブ読取＋ReportLab 描画のブロッキングを
        イベントループに載せない・アーカイブ系エンドポイントと同じ流儀）。

        保育経過記録（年間マトリクス）は、同じ子の保存済み保育経過記録をアーカイブ（record_store）から引いて
        過去期の列も自動で埋める（同じ年度だけ・割当は chohyo_pdf の純関数。アーカイブ未接続/該当なしは
        従来どおり今回の期のみ＝降格）。描画のみ（型の保証は harness）。kind/entry 不正は 400
        （握りつぶさず可視化）。LLM 非課金で非ゲート。
        """
        past_entries: list[dict] = []
        official_name: str | None = None
        # 保育要録/保育経過記録の氏名欄は本名（姓＋名）で描く＝児童マスタから解決（AI は生成しない・§14）。
        # 未接続/未登録は None＝従来どおり呼び名（child_id）へ降格。
        if req.kind in ("child_record", "nursery_record"):
            child = str(req.entry.get("child_id") or "").strip()
            if child:
                master = record_store.get_child(child)
                official_name = (master or {}).get("official_name") or None
                if req.kind == "child_record":
                    past_entries = record_store.list_child_record_entries(child)
        try:
            pdf = render_pdf(req.kind, req.entry, past_entries, official_name=official_name)
        except ValueError as e:
            return JSONResponse({"error": str(e), "code": "invalid_request"}, status_code=400)
        filename = _doc_filename(req.kind, req.entry, "pdf")
        # ASCII フォールバック＋RFC5987（UTF-8）で日本語ファイル名を両載せする。
        disposition = f"attachment; filename=\"document.pdf\"; filename*=UTF-8''{quote(filename)}"
        return Response(
            content=pdf,
            media_type="application/pdf",
            headers={"Content-Disposition": disposition},
        )

    @app.post("/api/export-docx")
    def web_export_docx(req: ExportPdfRequest):
        """確定 entry を園の実 Word 様式（.docx）へ流し込んで返す（Word 編集用の最終形・§11/§18）。

        帳票PDF（`/api/export-pdf`）が「綴じる確定版」なのに対し、こちらは保育士が Word で微修正・
        印刷できる編集版。実体は web/docx_fill（python-docx で `web/templates/*.docx` を埋めるだけ・
        描画のみ＝型の保証は harness＝§5）。docx→PDF のサーバ変換はしない（重い依存を持ち込まない）。
        未対応 kind・entry 不正は 400（握りつぶさず可視化）。LLM 非課金で非ゲート。
        """
        try:
            data = fill_docx(req.kind, req.entry)
        except ValueError as e:
            return JSONResponse({"error": str(e), "code": "invalid_request"}, status_code=400)
        filename = _doc_filename(req.kind, req.entry, "docx")
        disposition = f"attachment; filename=\"document.docx\"; filename*=UTF-8''{quote(filename)}"
        return Response(
            content=data,
            media_type=("application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
            headers={"Content-Disposition": disposition},
        )

    # ── アップロード取込（ファイル → LLM 解析 → 既存スキーマ・「書類を見る」タブ・§11）──────────
    # 種別（kind）は保育士がフォルダで選択済み＝1スキーマに固定。対象キー・child・age_band は与件
    # （フォームで指定）で、upload_parse が権威的に上書きしてから harness.finalize_entry で検査・整形する。
    # LLM を回す口なのでパスコードゲート（_GATED_PREFIX に /api/parse-upload を追加済み）。保存は後段の
    # /api/records（record_store・author_kind="imported"）で行い、ここは解析結果を返すだけ（中継・§5）。
    @app.post("/api/parse-upload")
    async def web_parse_upload(
        file: UploadFile = File(...),
        kind: str = Form("diary"),
        target: str = Form(""),
        child: str = Form(""),
        age_band: str = Form(""),
    ):
        """アップロードされたファイルを解析し、確認・編集用の entry（＋整形/検査結果）を返す。

        未対応形式・未対応種別は 400（握りつぶさない）。creds 未設定/LLM 失敗は 200＋parse_error で
        正直に降格し、フォームは与件入りの最小 entry で描ける（偽の緑を出さない）。
        """
        data = await file.read()
        try:
            return await parse_uploaded_file(
                kind,
                file.filename or "",
                file.content_type,
                data,
                target=target.strip(),
                child=child.strip(),
                age_band=age_band.strip(),
            )
        except ValueError as e:
            return JSONResponse({"error": str(e), "code": "invalid_request"}, status_code=400)

    # ── 書類アーカイブ（harness/record_store の中継・Phase 1）───────────────────────────
    # sync def＝FastAPI が threadpool で回す（同期 DB I/O でイベントループを塞がない）。
    # now の注入だけが runtime 境界（record_store は clock を持たない＝§5 の流儀）。

    def _resolve_actor(request: Request, declared: str, now: datetime) -> str:
        """証跡の actor を決める：IAP の検証済み email ＞ 自己申告（Phase 1 のつなぎ・Phase 3）。

        IAP identity があれば users へ auto-provision し、display_name 設定済みなら
        「表示名（email）」で残す＝読める証跡と偽装不可の identity を両立。IAP 未配線は従来どおり。
        """
        email = verified_iap_email(request)
        if not email:
            return declared
        user = record_store.touch_user(email, now=now)
        display = str(user.get("display_name") or "").strip()
        return f"{display}（{email}）" if display else email

    @app.post("/api/records")
    def web_save_record(req: RecordSaveRequest, request: Request) -> dict:
        """確定書類をアーカイブへ保存（AI 確定＝finalize / 保育士編集＝edit の版を積む）。"""
        now = datetime.now()
        return record_store.save_document(
            req.kind,
            req.entry,
            req.rendered_text,
            author_kind=req.author_kind,
            actor=_resolve_actor(request, req.actor, now),
            now=now,
        )

    @app.post("/api/records/approve")
    def web_approve_record(req: RecordApproveRequest, request: Request) -> dict:
        """書類を承認済みにし証跡を残す（actor＝IAP の検証済み email ＞ 自己申告）。"""
        now = datetime.now()
        return record_store.approve_document(
            req.kind, req.entry, actor=_resolve_actor(request, req.actor, now), now=now
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
        """期間内の日誌 entry（最新版 JSON）＝月案 L2／保育経過記録 L3 の seed 取得口。

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

    @app.get("/api/records/child-record-entries")
    def web_list_child_record_entries(child: str) -> dict:
        """指定児の保育経過記録（最新版・期間順）＝保育要録 L4 の seed 取得口（§19）。

        リテラル路なので `/api/records/{document_id}` より前に宣言し優先させる（diary-entries と同じ）。
        フロントは entries が空/未接続ならサンプル seed へ降格する（黙って空 seed で回さない）。
        """
        return {
            "entries": record_store.list_child_record_entries(child),
            "store": record_store.store_status(),
        }

    @app.get("/api/records/{document_id}")
    def web_get_record(document_id: str):
        """単一書類の全文（現行版の整形テキスト＋本文 entry）＝「書類を見る」タブの詳細。

        リテラル路（/api/records/diary-entries）より後に宣言し、そちらを優先させる（UUID なので実害は
        ないが順序で担保）。未接続/不在/不正 id は 404（偽の中身を出さない）。読取なので非ゲート。
        """
        doc = record_store.get_document(document_id)
        if doc is None:
            return JSONResponse(
                {"error": "書類が見つかりません", "code": "not_found"}, status_code=404
            )
        return doc

    @app.get("/api/children")
    def web_list_children() -> dict:
        """児童マスタ（アーカイブから auto-create された子）。未設定は空＝フロントは従来チップへ降格。"""
        return {"children": record_store.list_children(), "store": record_store.store_status()}

    @app.post("/api/children")
    def web_add_child(req: ChildAddRequest):
        """新規児を児童マスタへ登録する（未登録名を選んだとき・書込ゲート＝辞書荒らしと同枠）。

        呼び名（名）＋敬称（性別導出）＝display_name を harness が合成し upsert する（合成の実体は
        record_store＝境界に1つ）。given_name 空は 400。降格（DB 未設定）は skipped を正直に返す
        （フロントはセッション内のみ選択肢へ足す）。gender 不正（male/female 以外）は 400。
        """
        given = (req.given_name or "").strip()
        if not given:
            return JSONResponse(
                {"status": "error", "detail": "名（呼び名）は必須です"}, status_code=400
            )
        gender = (req.gender or "").strip()
        if gender and gender not in record_store.GENDERS:
            return JSONResponse(
                {"status": "error", "detail": f"性別が不正です: {req.gender!r}"}, status_code=400
            )
        display_name = record_store.compose_display_name(given, gender)
        result = record_store.upsert_child(
            display_name,
            family_name=req.family_name,
            given_name=given,
            gender=gender or None,
            now=datetime.now(),
        )
        result["display_name"] = display_name
        result["store"] = record_store.store_status()
        return result

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
