"""書類アーカイブ＝確定書類・児童マスタ・監査証跡の決定的ストア（Cloud SQL PostgreSQL）。

設計コンテキスト §5（決定ロジックの実体は harness に1つ）／§19（集積階層 日誌→月案→児童票の下流再構成）。
本番運用ブラッシュアップ Phase 1（2026-07）：確定した日誌/月案/児童票を session state 止まりにしない
永続アーカイブ。L2/L3 seed（前月・期間日誌）の取得元・児童マスタ・承認証跡（audit_events）を担う。

守る線（§5・既存の流儀）:
- LLM を呼ばない。パイプライン（FinalizeAgent）からも呼ばない＝LLM 系は不変で eval/E2E に影響しない。
  永続化はフロント→web API→本モジュールの明示フロー（web は薄い中継・決定的実体はここに1つ）。
- `DATABASE_URL` 未設定は降格：書込は {"status": "skipped"}・読取は空（RAG/Memory/GCS と同じ哲学）。
  設定済みで DB 障害なら書込は {"status": "error"}（UI に正直に出す・黙って握りつぶさない）。
- 書類本文は pydantic dump の JSON（PostgreSQL では JSONB）を SSOT とし、検索キー
  （doc_type / child / 対象期間 / status）だけ列に昇格する（射影テーブルは作らない＝二重表現しない）。
- child_id の橋渡し：書類 JSON 内の child_id は表示名のまま（LLM/eval 側は不変）。children.id（UUID）
  への解決は保存時の display_name lookup/auto-create ＝ harness 境界に1つ。
- clock は外部注入（policy_store と同じ）。actor（担当者）は呼び出し側が渡す（自己申告・認証は Phase 3=IAP）。

スキーマ適用は Alembic（repo root の `migrations/`・`uv run alembic upgrade head`）。テストは sqlite で
`Base.metadata.create_all` を使い creds 不要・決定論で回す（tests/test_harness/test_record_store.py）。
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

# ──────────────────────────── ORM モデル（テーブル定義の SSOT） ────────────────────────────

# PostgreSQL では JSONB、テスト（sqlite）では素の JSON にフォールバックする。
_JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")

DOC_KINDS = ("diary", "monthly", "child_record")
AUTHOR_KINDS = ("ai", "caregiver")
# 監査アクション：finalize（AI 確定の保存）/ edit（保育士編集の保存）/ approve（承認）
AUDIT_ACTIONS = ("finalize", "edit", "approve")


class Base(DeclarativeBase):
    pass


class Child(Base):
    """児童マスタ。実名（official_name）は DB のみに置き repo/eval へ持ち込まない（§14）。"""

    __tablename__ = "children"

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    display_name: Mapped[str] = mapped_column(sa.String(100), unique=True)
    official_name: Mapped[str | None] = mapped_column(sa.String(100))
    birthdate: Mapped[date | None] = mapped_column(sa.Date)
    active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime)
    updated_at: Mapped[datetime] = mapped_column(sa.DateTime)


class DocumentRecord(Base):
    """書類の存在と状態（1行＝1書類）。本文は versions 側の JSON が SSOT。

    dedupe_key＝`doc_type|child表示名|対象期間` の決定的な同一性キー。unique 制約の NULL 扱いが
    方言で揺れる（PostgreSQL は NULL 同士を別物と見なす）ため、列の組ではなく単一キーで担保する。
    """

    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    doc_type: Mapped[str] = mapped_column(sa.String(20), index=True)
    dedupe_key: Mapped[str] = mapped_column(sa.String(200), unique=True)
    child_id: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("children.id"), index=True)
    target_date: Mapped[date | None] = mapped_column(sa.Date, index=True)  # 日誌
    target_month: Mapped[str | None] = mapped_column(sa.String(7))  # 月案（YYYY-MM）
    target_period: Mapped[str | None] = mapped_column(sa.String(50))  # 児童票（期間・自由記述）
    status: Mapped[str] = mapped_column(sa.String(20), default="finalized")  # finalized/approved
    current_version_id: Mapped[uuid.UUID | None] = mapped_column(sa.Uuid)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime)
    updated_at: Mapped[datetime] = mapped_column(sa.DateTime)


class DocumentVersion(Base):
    """版ごとの本文。AI 生成（ai）と保育士編集（caregiver）を版として区別して残す＝
    将来の improver 入力（修正差分）・eval ケース拡充の一次データ（§12）。"""

    __tablename__ = "document_versions"
    __table_args__ = (sa.UniqueConstraint("document_id", "seq"),)

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("documents.id"), index=True)
    seq: Mapped[int] = mapped_column(sa.Integer)
    entry: Mapped[dict] = mapped_column(_JSON)  # pydantic dump（本文の SSOT）
    rendered_text: Mapped[str] = mapped_column(
        sa.Text, default=""
    )  # write_draft の標準様式テキスト
    author_kind: Mapped[str] = mapped_column(sa.String(20))  # ai / caregiver
    created_by: Mapped[str] = mapped_column(sa.String(100), default="")  # 担当者（自己申告）
    created_at: Mapped[datetime] = mapped_column(sa.DateTime)


class AuditEvent(Base):
    """誰が・いつ・何をしたか（承認・編集・確定の証跡）。actor は自己申告（認証導入＝Phase 3 で users と突合）。"""

    __tablename__ = "audit_events"

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("documents.id"), index=True)
    actor: Mapped[str] = mapped_column(sa.String(100), default="")
    action: Mapped[str] = mapped_column(sa.String(30))
    detail: Mapped[dict] = mapped_column(_JSON, default=dict)
    at: Mapped[datetime] = mapped_column(sa.DateTime, index=True)


# ──────────────────────────── engine（config が唯一の出所・未設定は降格） ────────────────────────────

_ENGINES: dict[str, sa.Engine] = {}


def _database_url() -> str:
    """接続 URL（未設定は空文字＝降格）。config が唯一の出所（policy_store._store_uri と同じ流儀）。"""
    from ..config import settings  # 遅延 import（テストの monkeypatch・循環回避）

    return settings.database_url.strip()


def _engine() -> sa.Engine | None:
    url = _database_url()
    if not url:
        return None
    if url not in _ENGINES:
        # Cloud Run（複数リクエスト並行）でも素直に働く控えめなプール。sqlite（テスト）はそのまま。
        _ENGINES[url] = sa.create_engine(url, pool_pre_ping=True)
    return _ENGINES[url]


def reset_engine_cache() -> None:
    """テスト用：URL 差し替え後に engine キャッシュを破棄する。"""
    for eng in _ENGINES.values():
        eng.dispose()
    _ENGINES.clear()


def store_status() -> str:
    """ストアの状態を正直に返す（UI が偽の永続を出さないため・policy_store.store_status と同じ哲学）。

    - "disabled"    … DATABASE_URL 未設定（降格＝永続化しない）。
    - "ok"          … 接続確認済み。
    - "unavailable" … 設定済みだが到達不能/未マイグレーション。
    """
    eng = _engine()
    if eng is None:
        return "disabled"
    try:
        with eng.connect() as conn:
            conn.execute(sa.select(sa.func.count()).select_from(DocumentRecord.__table__))
        return "ok"
    except SQLAlchemyError:
        return "unavailable"


# ──────────────────────────── 純関数（kind→キー抽出・child 解決） ────────────────────────────


def _extract_target(kind: str, entry: dict) -> tuple[date | None, str | None, str | None]:
    """entry から対象期間キー（target_date / target_month / target_period）を決定的に取り出す。

    欠落は ValueError（fail-loud＝アーカイブの同一性キーを黙って空にしない）。
    """
    if kind == "diary":
        raw = str(entry.get("date") or "").strip()
        if not raw:
            raise ValueError("日誌 entry に date（記録日）がありません")
        return date.fromisoformat(raw), None, None
    if kind == "monthly":
        month = str(entry.get("month") or "").strip()
        if not month:
            raise ValueError("月案 entry に month（対象月）がありません")
        return None, month, None
    if kind == "child_record":
        period = str(entry.get("period") or "").strip()
        if not period:
            raise ValueError("児童票 entry に period（対象期間）がありません")
        return None, None, period
    raise ValueError(f"kind は {DOC_KINDS} のいずれか: {kind!r}")


def _extract_child_display(kind: str, entry: dict) -> str:
    """書類の主対象の子ども表示名（日誌はクラス単位なので空）。"""
    if kind == "diary":
        return ""
    return str(entry.get("child_id") or "").strip()


def _mentioned_children(kind: str, entry: dict) -> list[str]:
    """entry に登場する子ども表示名（児童マスタの auto-create 対象）。重複除去・順序保持。"""
    names: list[str] = []
    main = _extract_child_display(kind, entry)
    if main:
        names.append(main)
    if kind == "diary":
        for note in entry.get("individual_notes") or []:
            name = str((note or {}).get("child_id") or "").strip()
            if name and name not in names:
                names.append(name)
        for att in entry.get("attendance") or []:
            name = str((att or {}).get("child_id") or "").strip()
            if name and name not in names:
                names.append(name)
    return names


def _dedupe_key(kind: str, child_display: str, entry: dict) -> str:
    d, m, p = _extract_target(kind, entry)
    target = d.isoformat() if d else (m or p or "")
    return f"{kind}|{child_display}|{target}"


def _resolve_child(session: Session, display_name: str, now: datetime) -> Child:
    """表示名→児童マスタ行（無ければ auto-create）。名前→UUID 解決の唯一の境界。"""
    child = session.scalar(sa.select(Child).where(Child.display_name == display_name))
    if child is None:
        child = Child(display_name=display_name, created_at=now, updated_at=now)
        session.add(child)
        session.flush()
    return child


def _find_document(session: Session, kind: str, entry: dict) -> DocumentRecord | None:
    key = _dedupe_key(kind, _extract_child_display(kind, entry), entry)
    return session.scalar(sa.select(DocumentRecord).where(DocumentRecord.dedupe_key == key))


# ──────────────────────────── 書込 API（web から中継・actor/now は外部注入） ────────────────────────────


def save_document(
    kind: str,
    entry: dict,
    rendered_text: str = "",
    *,
    author_kind: str = "ai",
    actor: str = "",
    now: datetime,
) -> dict:
    """確定書類を保存する（同一書類は版を積む upsert）。

    - 同一性は dedupe_key（doc_type × 子ども表示名 × 対象期間）。既存なら新しい版（seq+1）を追加し
      current_version を進める。承認済み（approved）の書類も編集保存で版は積める（証跡が残る）。
    - author_kind="ai"（AI 確定）→ audit action=finalize / "caregiver"（編集保存）→ action=edit。
    - entry に登場する子どもは児童マスタへ auto-create（表示名→UUID 解決はここに1つ）。

    Returns:
        {"status": "saved", "document_id", "version_seq", "doc_status"} ／
        {"status": "skipped"}（未設定降格）／{"status": "error", "detail"}（不正入力・DB 障害）
    """
    eng = _engine()
    if eng is None:
        return {"status": "skipped", "reason": "DATABASE_URL 未設定（アーカイブ降格）"}
    if author_kind not in AUTHOR_KINDS:
        return {
            "status": "error",
            "detail": f"author_kind は {AUTHOR_KINDS} のいずれか: {author_kind!r}",
        }
    try:
        target_date, target_month, target_period = _extract_target(kind, entry)
        child_display = _extract_child_display(kind, entry)
        key = _dedupe_key(kind, child_display, entry)
        with Session(eng) as session, session.begin():
            for name in _mentioned_children(kind, entry):
                _resolve_child(session, name, now)
            doc = session.scalar(sa.select(DocumentRecord).where(DocumentRecord.dedupe_key == key))
            if doc is None:
                doc = DocumentRecord(
                    doc_type=kind,
                    dedupe_key=key,
                    child_id=(
                        _resolve_child(session, child_display, now).id if child_display else None
                    ),
                    target_date=target_date,
                    target_month=target_month,
                    target_period=target_period,
                    created_at=now,
                    updated_at=now,
                )
                session.add(doc)
                session.flush()
            last_seq = session.scalar(
                sa.select(sa.func.max(DocumentVersion.seq)).where(
                    DocumentVersion.document_id == doc.id
                )
            )
            version = DocumentVersion(
                document_id=doc.id,
                seq=(last_seq or 0) + 1,
                entry=entry,
                rendered_text=rendered_text,
                author_kind=author_kind,
                created_by=actor,
                created_at=now,
            )
            session.add(version)
            session.flush()
            doc.current_version_id = version.id
            doc.updated_at = now
            session.add(
                AuditEvent(
                    document_id=doc.id,
                    actor=actor,
                    action="finalize" if author_kind == "ai" else "edit",
                    detail={"version_seq": version.seq},
                    at=now,
                )
            )
            return {
                "status": "saved",
                "document_id": str(doc.id),
                "version_seq": version.seq,
                "doc_status": doc.status,
            }
    except (ValueError, SQLAlchemyError) as e:
        return {"status": "error", "detail": str(e)}


def approve_document(kind: str, entry: dict, *, actor: str, now: datetime) -> dict:
    """書類を承認済み（approved）にし、証跡（audit action=approve）を残す。

    対象は dedupe_key で特定する（未保存なら error＝先に save_document）。
    """
    eng = _engine()
    if eng is None:
        return {"status": "skipped", "reason": "DATABASE_URL 未設定（アーカイブ降格）"}
    try:
        with Session(eng) as session, session.begin():
            doc = _find_document(session, kind, entry)
            if doc is None:
                return {"status": "error", "detail": "対象の書類がアーカイブにありません（未保存）"}
            doc.status = "approved"
            doc.updated_at = now
            session.add(
                AuditEvent(document_id=doc.id, actor=actor, action="approve", detail={}, at=now)
            )
            return {"status": "approved", "document_id": str(doc.id)}
    except (ValueError, SQLAlchemyError) as e:
        return {"status": "error", "detail": str(e)}


# ──────────────────────────── 読取 API（降格＝空・L2/L3 seed の取得元） ────────────────────────────


def _doc_view(doc: DocumentRecord, child_display: str | None) -> dict:
    return {
        "id": str(doc.id),
        "doc_type": doc.doc_type,
        "child": child_display or "",
        "target": (
            doc.target_date.isoformat()
            if doc.target_date
            else (doc.target_month or doc.target_period or "")
        ),
        "status": doc.status,
        "updated_at": doc.updated_at.isoformat(),
    }


def list_documents(
    doc_type: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = 200,
) -> list[dict]:
    """書類メタの一覧（新しい順）。降格・障害は空（読取は落とさない＝read_policy と同じ）。"""
    eng = _engine()
    if eng is None:
        return []
    try:
        with Session(eng) as session:
            q = sa.select(DocumentRecord).order_by(DocumentRecord.updated_at.desc()).limit(limit)
            if doc_type:
                q = q.where(DocumentRecord.doc_type == doc_type)
            if date_from:
                q = q.where(DocumentRecord.target_date >= date_from)
            if date_to:
                q = q.where(DocumentRecord.target_date <= date_to)
            docs = list(session.scalars(q))
            names = {c.id: c.display_name for c in session.scalars(sa.select(Child))}
            return [_doc_view(d, names.get(d.child_id)) for d in docs]
    except SQLAlchemyError:
        return []


def list_diary_entries(
    date_from: date,
    date_to: date,
    *,
    approved_only: bool = False,
) -> list[dict]:
    """期間内の日誌の最新版 entry（JSON）を日付順に返す＝月案 L2／児童票 L3 の seed 取得元。

    集計そのもの（child_id 別の decomposition）は従来どおり harness/aggregate（DigestPrepAgent）が
    担う＝ここは「期間の日誌本文を引く」だけ（責務を重ねない）。
    """
    eng = _engine()
    if eng is None:
        return []
    try:
        with Session(eng) as session:
            q = (
                sa.select(DocumentRecord)
                .where(
                    DocumentRecord.doc_type == "diary",
                    DocumentRecord.target_date >= date_from,
                    DocumentRecord.target_date <= date_to,
                )
                .order_by(DocumentRecord.target_date)
            )
            if approved_only:
                q = q.where(DocumentRecord.status == "approved")
            entries: list[dict] = []
            for doc in session.scalars(q):
                version = session.scalar(
                    sa.select(DocumentVersion).where(DocumentVersion.id == doc.current_version_id)
                )
                if version is not None:
                    entries.append(version.entry)
            return entries
    except SQLAlchemyError:
        return []


def list_children() -> list[dict]:
    """児童マスタ（active のみ・表示名順）。UI の子ども選択肢（降格は空＝従来チップへ）。"""
    eng = _engine()
    if eng is None:
        return []
    try:
        with Session(eng) as session:
            children = session.scalars(
                sa.select(Child).where(Child.active.is_(True)).order_by(Child.display_name)
            )
            return [
                {
                    "id": str(c.id),
                    "display_name": c.display_name,
                    "birthdate": c.birthdate.isoformat() if c.birthdate else None,
                }
                for c in children
            ]
    except SQLAlchemyError:
        return []


def list_audit_events(document_id: str | None = None, limit: int = 100) -> list[dict]:
    """監査証跡（新しい順）。承認・編集・確定の「誰が・いつ」を可視化する。"""
    eng = _engine()
    if eng is None:
        return []
    try:
        with Session(eng) as session:
            q = sa.select(AuditEvent).order_by(AuditEvent.at.desc()).limit(limit)
            if document_id:
                q = q.where(AuditEvent.document_id == uuid.UUID(document_id))
            return [
                {
                    "document_id": str(e.document_id) if e.document_id else None,
                    "actor": e.actor,
                    "action": e.action,
                    "detail": e.detail,
                    "at": e.at.isoformat(),
                }
                for e in session.scalars(q)
            ]
    except (ValueError, SQLAlchemyError):
        return []
