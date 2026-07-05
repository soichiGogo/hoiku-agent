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
from datetime import date, datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Mapped, Session, mapped_column

from . import db

# ──────────────────────────── ORM モデル（テーブル定義の SSOT） ────────────────────────────

# 接続基盤（engine キャッシュ・Base・JSONB variant）は harness/db.py で policy_store と共有する。
# 既存の公開名（Base / _engine / reset_engine_cache）は互換のため本モジュールから引き続き使える。
Base = db.Base
_JSON = db.JSON_VARIANT

DOC_KINDS = ("diary", "monthly", "child_record")
AUTHOR_KINDS = ("ai", "caregiver")
# 監査アクション：finalize（AI 確定の保存）/ edit（保育士編集の保存）/ approve（承認）
AUDIT_ACTIONS = ("finalize", "edit", "approve")


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
    """誰が・いつ・何をしたか（承認・編集・確定の証跡）。

    actor は自己申告（Phase 1 のつなぎ）だが、IAP（Phase 3）配下では web が検証済みの Google
    アカウント email を渡す＝偽装不可の証跡になる（どちらが来たかは users への登録有無で分かる）。
    """

    __tablename__ = "audit_events"

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("documents.id"), index=True)
    actor: Mapped[str] = mapped_column(sa.String(100), default="")
    action: Mapped[str] = mapped_column(sa.String(30))
    detail: Mapped[dict] = mapped_column(_JSON, default=dict)
    at: Mapped[datetime] = mapped_column(sa.DateTime, index=True)


class User(Base):
    """認証済みユーザー（IAP の Google アカウント・Phase 3）。

    IAP を通った email を初回アクセス時に auto-provision し（children と同じ流儀）、
    display_name（園内での呼び名）を後から DB で設定できるようにする。v0 では認可（ロール別の
    権限制御）は持たない＝identity の記録と表示名の対応だけ（承認フローの多段化は将来）。
    """

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(sa.String(200), unique=True)
    display_name: Mapped[str] = mapped_column(sa.String(100), default="")
    active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime)
    updated_at: Mapped[datetime] = mapped_column(sa.DateTime)


# ──────────────────────────── engine（実体は harness/db.py・config が唯一の出所） ────────────────────────────

_engine = db.engine
reset_engine_cache = db.reset_engine_cache


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


# ──────────────────────────── 純関数（kind→キー抽出・期間パース・child 解決） ────────────────────────────


def month_date_range(month: str) -> tuple[date, date]:
    """ "YYYY-MM" → その月の（初日, 末日）。L2 seed（前月日誌）の範囲クエリ用。不正は ValueError。"""
    y, m = (int(x) for x in month.strip().split("-"))
    first = date(y, m, 1)
    last = date(y + (m == 12), (m % 12) + 1, 1) - timedelta(days=1)
    return first, last


def prev_month_of(month: str) -> str:
    """ "YYYY-MM" → 前月の "YYYY-MM"（月案の L2 seed＝前月日誌の対象月）。不正は ValueError。"""
    y, m = (int(x) for x in month.strip().split("-"))
    if not 1 <= m <= 12:
        raise ValueError(f"month が不正です: {month!r}")
    return f"{y - (m == 1)}-{(m - 2) % 12 + 1:02d}"


def period_date_range(period: str) -> tuple[date, date] | None:
    """児童票の期間（例 "2026-04〜2026-06"。〜/~/− 区切り）→（開始月初日, 終了月末日）。

    期制は園差＝自由記述（§19）なので、月〜月の形だけ決定的に解釈し、それ以外は None を返す
    （呼び出し側がサンプル/手渡し seed へ降格する＝黙って誤解釈しない）。
    """
    raw = period.strip()
    for sep in ("〜", "~", "−", "―"):
        if sep in raw:
            start_s, _, end_s = raw.partition(sep)
            try:
                start, _ = month_date_range(start_s)
                _, end = month_date_range(end_s)
            except ValueError:
                return None
            return (start, end) if start <= end else None
    return None


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


def touch_user(email: str, *, now: datetime) -> dict:
    """検証済みユーザー（IAP の email）を users へ auto-provision し、表示用情報を返す（Phase 3）。

    children と同じ流儀＝初回アクセス時に行を作る（登録画面を待たせない）。display_name は
    後から DB で設定でき、設定済みなら actor 表示に使える。降格・障害・空 email は
    {"status": "skipped"/"error"}（本流＝書類の保存・承認を壊さない）。
    """
    email = email.strip()
    eng = _engine()
    if eng is None or not email:
        return {"status": "skipped"}
    try:
        with Session(eng) as session, session.begin():
            user = session.scalar(sa.select(User).where(User.email == email))
            if user is None:
                user = User(email=email, created_at=now, updated_at=now)
                session.add(user)
                session.flush()
            return {
                "status": "ok",
                "email": user.email,
                "display_name": user.display_name,
                "active": user.active,
            }
    except SQLAlchemyError as e:
        return {"status": "error", "detail": str(e)}


def upsert_child(display_name: str, *, birthdate: date | None = None, now: datetime) -> dict:
    """児童マスタへ表示名で upsert する（無ければ作成・誕生日を補完）。冪等。

    表示名→children.id 解決の唯一の境界（`_resolve_child`）を共有する。園名簿の事前登録
    （seed）や表示名の後付け整備に使う想定＝**実名は扱わず display_name は仮名**（§14）。
    誕生日は年齢帯（0-2/3-5）自動判定の材料。既存行の誕生日は上書きしない（保育士が
    後から DB で整えた値を壊さない）＝未設定のときだけ補完する。降格・空名は skipped。
    """
    display_name = display_name.strip()
    eng = _engine()
    if eng is None or not display_name:
        return {"status": "skipped"}
    try:
        with Session(eng) as session, session.begin():
            existing = session.scalar(sa.select(Child).where(Child.display_name == display_name))
            created = existing is None
            child = _resolve_child(session, display_name, now)
            if birthdate is not None and child.birthdate is None:
                child.birthdate = birthdate
                child.updated_at = now
            return {
                "status": "created" if created else "exists",
                "id": str(child.id),
                "display_name": child.display_name,
                "birthdate": child.birthdate.isoformat() if child.birthdate else None,
            }
    except SQLAlchemyError as e:
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
    """書類メタの一覧（新しい順）。降格・障害は空（読取は落とさない＝policy_store の read と同じ）。"""
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


def list_child_record_entries(child_display_name: str) -> list[dict]:
    """指定児の児童票の最新版 entry（JSON）を期間順に返す＝年間マトリクス帳票の過去期埋め込み用。

    どの期をどの列に置くか（年度の同定・期→列の割当）は帳票描画側（web/chohyo_pdf）の責務で、
    ここは「その子の児童票を全部引く」だけ（責務を重ねない）。降格・障害・該当なしは空。
    """
    name = child_display_name.strip()
    eng = _engine()
    if eng is None or not name:
        return []
    try:
        with Session(eng) as session:
            child = session.scalar(sa.select(Child).where(Child.display_name == name))
            if child is None:
                return []
            q = (
                sa.select(DocumentRecord)
                .where(
                    DocumentRecord.doc_type == "child_record",
                    DocumentRecord.child_id == child.id,
                )
                .order_by(DocumentRecord.target_period)
            )
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
