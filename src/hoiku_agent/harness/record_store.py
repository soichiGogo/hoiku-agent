"""書類アーカイブ＝確定書類・児童マスタ・監査証跡の決定的ストア（Cloud SQL PostgreSQL）。

設計コンテキスト §5（決定ロジックの実体は harness に1つ）／§19（集積階層 日誌→月案→保育経過記録の下流再構成）。
本番運用ブラッシュアップ Phase 1（2026-07）：確定した日誌/月案/保育経過記録を session state 止まりにしない
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
- clock は外部注入（policy_store と同じ）。actor（担当者）は呼び出し側が渡す（自己申告・認証は Phase 3=Google Sign-In）。

スキーマ適用は Alembic（repo root の `migrations/`・`uv run alembic upgrade head`）。テストは sqlite で
`Base.metadata.create_all` を使い creds 不要・決定論で回す（tests/test_harness/test_record_store.py）。
"""

from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timedelta
from typing import Iterable

import sqlalchemy as sa
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Mapped, Session, mapped_column

from . import db

_logger = logging.getLogger(__name__)

# ──────────────────────────── ORM モデル（テーブル定義の SSOT） ────────────────────────────

# 接続基盤（engine キャッシュ・Base・JSONB variant）は harness/db.py で policy_store と共有する。
# 既存の公開名（Base / _engine / reset_engine_cache）は互換のため本モジュールから引き続き使える。
Base = db.Base
_JSON = db.JSON_VARIANT

DOC_KINDS = ("diary", "monthly", "class_monthly", "child_record", "nursery_record")
# 年齢帯（書類の年齢区分・schemas.enums.AgeBand の値と一致＝0–2:3つの視点/3–5:5領域）。
# クラスの属性ではなく、在籍児の生年月日と対象年度から導出する。record_store は schemas を引かない純
# ストアなので GENDERS と同じくローカル定数で持つ（値は単一の事実）。
AGE_BANDS = ("0-2", "3-5")
# 版の来歴：ai（AI が生成・確定）/ caregiver（保育士が編集して保存）/ imported（外部ファイルを
# 取り込んで保存＝「書類を見る」タブのアップロード取込。AI 生成でも保育士の AI 下書き編集でもない
# 第三の来歴なので混ぜない＝「修正差分の一次データ」を汚さない・§12/§19）。
AUTHOR_KINDS = ("ai", "caregiver", "imported")
# 監査アクション：finalize（AI 確定の保存）/ edit（保育士編集の保存）/ approve（承認）/ import（取込保存）
AUDIT_ACTIONS = ("finalize", "edit", "approve", "import")
# 版の来歴 → 監査アクションの対応（save_document が積む版の action）。
_AUTHOR_KIND_ACTION = {"ai": "finalize", "caregiver": "edit", "imported": "import"}
# 書類フィードバックの評定：up（👍＝良かった）/ down（👎＝直したい）。保育士が確定/承認画面から
# 送る軽量シグナル（§8「回す」の一次入力＋§12 eval 質的拡充の原資）。audit_events（操作の証跡）とは
# 関心事が別なので独立テーブルに持つ（同じ関心事を別の場所で二重に表現しない）。
FEEDBACK_VERDICTS = ("up", "down")
# ローカル CLI/テスト（Google Sign-In を使わない開発環境）のための固定ワークスペース。Web の本番経路は
# 必ず Google subject から解決した別 ID を明示して渡すため、公開環境で共有領域にはならない。
LOCAL_WORKSPACE_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")

# 性別→敬称（男→くん / 女→ちゃん 固定）。敬称は列で持たず gender を単一ソースにする（呼び名に付けて
# 表示名＝child_id を合成する）。園の実運用でも保育士が性別を選ぶだけで敬称のゆれ・重複児を防ぐ。
GENDERS = ("male", "female")
_HONORIFIC = {"male": "くん", "female": "ちゃん"}

# actor（担当者名／Google 表示名＋email）列は VARCHAR(100)。正当に長い表示名で PostgreSQL の書込が
# DataError にならないよう、書込境界で列上限に丸める（sqlite テストでは無害だが本番だけ落ちるのを防ぐ）。
_ACTOR_MAX = 100


def _clamp_actor(actor: str) -> str:
    return (actor or "")[:_ACTOR_MAX]


def honorific_for(gender: str | None) -> str:
    """性別から敬称を導く（male→くん / female→ちゃん / 不明→空）。表示名合成の単一ソース。"""
    return _HONORIFIC.get((gender or "").strip(), "")


def compose_display_name(given_name: str, gender: str | None) -> str:
    """呼び名（名）＋敬称＝日常の表示名（child_id が指す同定キー）。例 ("はると","male")→"はるとくん"。"""
    return f"{given_name.strip()}{honorific_for(gender)}"


def official_full_name(family_name: str | None, given_name: str | None) -> str:
    """姓＋名＝本名（保育要録/保育経過記録の氏名欄）。全角空白区切り・空要素は詰める（両方空なら空文字）。"""
    parts = [(family_name or "").strip(), (given_name or "").strip()]
    return "　".join(p for p in parts if p)


def age_months_label(birthdate: date, as_of: date) -> str:
    """生年月日と基準日から満年齢を「○歳○か月」で返す純関数（決定的＝月齢表示の実体はここに1つ）。

    保育経過記録などの「歳児」欄を粗い年齢帯（0-2/3-5）でなく子ども一人ひとりの満年齢で出すための計算。
    月は基準日の「日」が誕生日の「日」に満たなければ1つ繰り下げる（暦どおりの満年齢）。
    書式は既存の下書き/シード（例 "4歳0か月"・"1歳3か月"）に合わせ「歳」「か月」を用いる。
    基準日が生年月日より前（＝まだ生まれていない）のときは空文字を返す（誤表示より無表示）。
    """
    years = as_of.year - birthdate.year
    months = as_of.month - birthdate.month
    if as_of.day < birthdate.day:
        months -= 1
    if months < 0:
        years -= 1
        months += 12
    if years < 0:
        return ""
    return f"{years}歳{months}か月"


def age_band_for_birthdate(birthdate: date | None, as_of: date) -> str | None:
    """生年月日と基準日時点の満年齢から、書類用の年齢帯を導出する。

    クラスは年齢帯を保存しない。年度初日（4月1日）を基準に、0〜2歳を ``"0-2"``、3歳以上を
    ``"3-5"`` とする。生年月日が未登録、または基準日より後なら推測せず ``None`` を返す。
    """
    if birthdate is None:
        return None
    years = as_of.year - birthdate.year
    if (as_of.month, as_of.day) < (birthdate.month, birthdate.day):
        years -= 1
    if years < 0:
        return None
    return "0-2" if years <= 2 else "3-5"


def fiscal_year_start_for_year(fiscal_year: str, *, fallback: date | None = None) -> date:
    """年度文字列（YYYY）の4月1日を返す。空/不正は fallback の属する年度に降格する。"""
    try:
        year = int((fiscal_year or "").strip())
        if 1900 <= year <= 9999:
            return date(year, 4, 1)
    except ValueError:
        pass
    base = fallback or date.today()
    return date(base.year - (base.month < 4), 4, 1)


class Workspace(Base):
    """ユーザーごとに隔離するデータ領域。

    現時点は Google ユーザー1人につき個人ワークスペース1つ（共有招待は未実装）。書類・園児・
    クラスを同じ workspace_id で必ず絞り込むことが、アーカイブの認可境界になる。
    """

    __tablename__ = "workspaces"

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(sa.String(100), default="")
    is_legacy: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime)
    updated_at: Mapped[datetime] = mapped_column(sa.DateTime)


class Child(Base):
    """児童マスタ。本名（姓名）は DB のみに置き repo/eval へ持ち込まない（§14）。

    3 つの名前の要素を分けて持つ（一本の文字列に潰さない）:
    - `display_name`（呼び名＋敬称・例 "はるとくん"）… 日誌本文の主語・**child_id が指す同定キー**
      （UNIQUE）。書類 JSON 側は敬称込みのまま（LLM/eval は不変）。
    - `given_name`（名・呼び名）／`gender`（male/female）… 表示名＝`given_name`＋敬称（性別導出）を
      合成する素。既存行は migration 0006 が display_name の末尾敬称から back-fill する。
    - `family_name`（姓）… 保育要録/保育経過記録の**氏名欄**用の本名（姓＋名）。AI は生成せず保育士が入力。
    `official_name` は旧・単一氏名列で使っていない（family_name/given_name へ移行済み・互換のため残置）。
    """

    __tablename__ = "children"

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("workspaces.id"), index=True, default=LOCAL_WORKSPACE_ID
    )
    display_name: Mapped[str] = mapped_column(sa.String(100))  # 呼び名＋敬称＝child_id
    family_name: Mapped[str | None] = mapped_column(
        sa.String(50)
    )  # 姓（本名・氏名欄・§14 DB のみ）
    given_name: Mapped[str | None] = mapped_column(sa.String(50))  # 名（＝呼び名・表示名合成の素）
    gender: Mapped[str | None] = mapped_column(sa.String(10))  # male/female（敬称導出）
    official_name: Mapped[str | None] = mapped_column(sa.String(100))  # 旧・単一氏名（deprecated）
    birthdate: Mapped[date | None] = mapped_column(sa.Date)
    # 所属クラス（組）。園の名簿管理で保育士が割り当てる（日誌 roster・クラス月案の素）。v0 は
    # 「現在の所属」1本＝FK（年度またぎの履歴は書類 JSON が作成時の age_band/組名を既に保持するため
    # 不要＝migration 0007）。未所属は NULL（auto-create された児は未所属＝管理画面で割り当てる）。
    class_id: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("classes.id"), index=True)
    active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime)
    updated_at: Mapped[datetime] = mapped_column(sa.DateTime)


class Class(Base):
    """クラス（組）マスタ。園の名簿管理で保育士が定義し、児童を割り当てる（日誌 roster の素）。

    現状クラスは一次エンティティとして存在せず、書類 JSON 内の `class_name`（自由記述）と `age_band`
    でしか表現されていなかった。これを一次化して ① 日誌フォームの roster（在籍児の一括流し込み）②
    園児登録の受け皿 を支える。年齢帯はクラスの属性でなく、在籍児の生年月日と対象年度から導出する。

    同一性は (name, fiscal_year)＝同じ組名でも年度が違えば別クラス（進級で組名は再利用されるため）。
    児童との関係は `Child.class_id`（現在の所属1本・v0）で、年度またぎの履歴は持たない
    （§18 と同じ現場依存＝残課題）。
    """

    __tablename__ = "classes"
    __table_args__ = (sa.UniqueConstraint("workspace_id", "name", "fiscal_year"),)

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("workspaces.id"), index=True, default=LOCAL_WORKSPACE_ID
    )
    name: Mapped[str] = mapped_column(sa.String(50))  # 組名（例: ひまわり組）
    fiscal_year: Mapped[str] = mapped_column(sa.String(10), default="")  # 年度（例: 2026）
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
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("workspaces.id"), index=True, default=LOCAL_WORKSPACE_ID
    )
    doc_type: Mapped[str] = mapped_column(sa.String(20), index=True)
    dedupe_key: Mapped[str] = mapped_column(sa.String(200))
    child_id: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("children.id"), index=True)
    target_date: Mapped[date | None] = mapped_column(sa.Date, index=True)  # 日誌
    target_month: Mapped[str | None] = mapped_column(sa.String(7))  # 月案（YYYY-MM）
    target_period: Mapped[str | None] = mapped_column(
        sa.String(50)
    )  # 保育経過記録（期間・自由記述）
    status: Mapped[str] = mapped_column(sa.String(20), default="finalized")  # finalized/approved
    current_version_id: Mapped[uuid.UUID | None] = mapped_column(sa.Uuid)
    # Memory Bankへ同期済みの版。current_version_id と一致するときだけ現行版の同期完了を表す。
    # 編集でcurrent_version_idが進めば自動的に不一致となり、次の承認で新しい版を同期する。
    memory_synced_version_id: Mapped[uuid.UUID | None] = mapped_column(sa.Uuid, index=True)
    memory_synced_at: Mapped[datetime | None] = mapped_column(sa.DateTime)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime)
    updated_at: Mapped[datetime] = mapped_column(sa.DateTime)

    __table_args__ = (sa.UniqueConstraint("workspace_id", "dedupe_key"),)


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

    actor は自己申告（Phase 1 のつなぎ）だが、Google Sign-In（Phase 3）配下では web が検証済みの Google
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
    """認証済みユーザー（Google アカウント・Phase 3）。

    Google Sign-In で検証した subject（Google の不変 ID）を初回アクセス時に auto-provision し、
    email は表示・監査用の検証済み属性として紐づける（children と同じ流儀）。
    display_name（園内での呼び名）を後から DB で設定できるようにする。v0 では認可（ロール別の
    権限制御）は持たない＝identity の記録と表示名の対応だけ（承認フローの多段化は将来）。
    """

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(sa.String(200), unique=True)
    google_subject: Mapped[str | None] = mapped_column(sa.String(255), unique=True, nullable=True)
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("workspaces.id"), index=True
    )
    display_name: Mapped[str] = mapped_column(sa.String(100), default="")
    active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime)
    updated_at: Mapped[datetime] = mapped_column(sa.DateTime)


class Feedback(Base):
    """書類への保育士フィードバック（👍👎＋ひとこと）。確定/承認画面から送る軽量シグナル。

    「回す（改善サイクル）」の一次入力＝保育士が生成物を評価した生ログ（§4/§8 の入力＝「修正メモ・👍👎」）。
    ひとことは改善エージェント（improver）が指針カード化を判断する材料になり、👍👎 の生ログと修正差分は
    eval ケースの質的拡充の原資でもある（§12・別系統・自動注入はしない）。

    紐付けは **document（文書）＋ version（その時の版）** の両方。承認失効や後続編集で本文が変わっても
    「どの版への評価か」を曖昧にしない（版は document_versions.id・現行版をサーバ側で解決して埋める）。
    audit_events（誰が finalize/edit/approve/import したかの証跡）とは意味論が別なので独立テーブルにする。
    """

    __tablename__ = "feedback"

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("workspaces.id"), index=True, default=LOCAL_WORKSPACE_ID
    )
    document_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("documents.id"), index=True)
    # 評価対象の版（送信時点の現行版）。版が引けない稀な状態でも保存は落とさない＝nullable。
    version_id: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("document_versions.id"))
    verdict: Mapped[str] = mapped_column(sa.String(4))  # up / down
    comment: Mapped[str] = mapped_column(sa.Text, default="")  # ひとこと（任意）
    actor: Mapped[str] = mapped_column(
        sa.String(100), default=""
    )  # 担当者（Google 検証済み ＞ 自己申告）
    created_at: Mapped[datetime] = mapped_column(sa.DateTime, index=True)


class DeletionRequest(Base):
    """アカウント削除の受付記録。誤操作を避け、受付後30日で運営者が消去を実行する。"""

    __tablename__ = "deletion_requests"

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("workspaces.id"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("users.id"), index=True)
    email: Mapped[str] = mapped_column(sa.String(200))
    status: Mapped[str] = mapped_column(sa.String(20), default="pending")
    requested_at: Mapped[datetime] = mapped_column(sa.DateTime, index=True)
    due_at: Mapped[datetime] = mapped_column(sa.DateTime, index=True)
    processed_at: Mapped[datetime | None] = mapped_column(sa.DateTime)


# ──────────────────────────── engine（実体は harness/db.py・config が唯一の出所） ────────────────────────────

_engine = db.engine
reset_engine_cache = db.reset_engine_cache


def _write_error(exc: Exception) -> dict:
    """書込系の例外を安定した error dict へ。

    テーブル/カラム不在（＝migration 未適用の典型・§ prod-db-migration-drift）は生の psycopg 文字列を
    UI に出さず、専用コード＋対処を返す（record_store は fail-loud だが、露出する文言は保育士に意味が
    通るものにする）。それ以外は従来どおり詳細を返す。分類は harness/db に1つ。
    """
    if db.is_missing_schema_error(exc):
        return {
            "status": "error",
            "code": "db_schema_unready",
            "detail": (
                "書類アーカイブのデータベースが未整備です（DB migration 未適用の可能性）。"
                "本番 DB に alembic upgrade head を適用してください。"
            ),
        }
    if isinstance(exc, ValueError):
        # 入力検証エラー（欠落キー・不正 kind 等）＝こちらが生成した安全な文言（SQL/投入値を含まない）。
        # 保育士が原因を直せるようそのまま返す。
        return {"status": "error", "detail": str(exc)}
    # それ以外の DB 障害（SQLAlchemyError）：str(exc) は [SQL: ...] [parameters: (...)] を含み、
    # 内部スキーマ・SQL 構造に加え投入値（フィードバックのコメント・actor 名・entry 断片）まで
    # API 応答へ露出する。詳細はサーバログにのみ残し、UI へは一般化した文言＋識別コードを返す。
    _logger.exception("record_store 書込エラー")
    return {
        "status": "error",
        "code": "db_write_failed",
        "detail": "保存に失敗しました。時間をおいて再試行してください。",
    }


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
    """保育経過記録の期間（例 "2026-04〜2026-06"。〜/~/− 区切り）→（開始月初日, 終了月末日）。

    期制は園差＝自由記述（§19）なので、月〜月の形だけ決定的に解釈し、それ以外は None を返す
    （呼び出し側がサンプル/手渡し seed へ降格する＝黙って誤解釈しない）。
    """
    raw = period.strip()
    # 区切り候補：波ダッシュ U+301C・チルダ・全角チルダ U+FF5E（Windows IME 既定で最頻出）・
    # マイナス記号 U+2212・全角ダッシュ U+2015・EN DASH U+2013。取込・手入力の表記ゆれ1つで当該期が
    # covered_until/年間マトリクスに寄与しなくなるのを防ぐ。ハイフンマイナスは日付 YYYY-MM 内に
    # 含まれ partition が誤分割するため区切りには入れない。
    for sep in ("〜", "~", "～", "−", "―", "–"):
        if sep in raw:
            start_s, _, end_s = raw.partition(sep)
            try:
                start, _ = month_date_range(start_s)
                _, end = month_date_range(end_s)
            except ValueError:
                return None
            return (start, end) if start <= end else None
    return None


def covered_until(periods: Iterable[str]) -> date | None:
    """保育経過記録の期間群から「経過記録に反映済みの最終日」を決定的に求める（クラス月案の未反映判定用）。

    各期間を `period_date_range` で解釈し、その終了日の最大値を返す。解釈不能な期間（自由記述で
    月〜月の形でない）は境界に寄与しない＝その分の日誌は「未反映」として安全側に残る（情報を落とさない）。
    期間が1つも解釈できなければ None（＝全日誌が未反映）。年度は日付比較なので自然に跨ぐ。
    """
    latest: date | None = None
    for period in periods:
        span = period_date_range(period)
        if span is None:
            continue
        if latest is None or span[1] > latest:
            latest = span[1]
    return latest


def covered_until_by_child(records: Iterable[dict]) -> dict[str, date]:
    """保育経過記録群を child_id 別に見て、各児の「反映済み最終日」を返す（クラス月案の未反映判定＝児童別）。

    クラス一律の `covered_until`（全児の max）だと、記録が進んでいる児に引きずられて記録が遅れている児
    （途中入園児等）の日誌まで反映済み扱いで落ちる。児童別に境界を持つことで、各児の日誌を「その児の
    経過記録に未反映の分」だけ残せる（§19 依存モデル 2026-07 の安全側＝情報を落とさない）。
    解釈不能な期・child_id 不明のレコードは寄与しない。記録が1件も無い児は返り値に現れない
    （＝境界なし＝その児の全日誌が未反映として集積に残る）。
    """
    by_child: dict[str, date] = {}
    for r in records:
        if not isinstance(r, dict):
            continue
        child = str(r.get("child_id") or "").strip()
        span = period_date_range(str(r.get("period") or ""))
        if not child or span is None:
            continue
        end = span[1]
        if child not in by_child or end > by_child[child]:
            by_child[child] = end
    return by_child


def fiscal_year_start(month: str) -> date:
    """対象月（YYYY-MM）が属する年度（4月始まり）の初日を返す（不正 month は ValueError）。

    クラス月案の未反映日誌の探索下限＝**同一コホートに限る境界**。同じ年齢帯でも前年度は別の子集団
    （進級して抜ける）なので、年度初めより前の日誌は拾わない（前年度コホートの混入を防ぐ）。
    """
    m = normalize_month(month)
    year, mm = int(m[:4]), int(m[5:7])
    fy = year if mm >= 4 else year - 1
    return date(fy, 4, 1)


def normalize_month(month: str) -> str:
    """ "YYYY-M"／"YYYY-MM" → ゼロ詰め "YYYY-MM" に正規化する（不正は ValueError＝fail-loud）。

    下流（class_plan_history_digest の月順ソート・list_class_monthly_entries の `target_month < before_month`
    文字列比較・dedupe_key）はゼロ詰め YYYY-MM を決定的前提にしている。LLM が "2026-7" と echo しても
    "2026-07" と一致させ、辞書順比較・同一性キーの前提を構造的に守る（diary の date.fromisoformat と対称）。
    """
    y_s, sep, m_s = month.strip().partition("-")
    if not sep:
        raise ValueError(f"month は YYYY-MM 形式が必要です: {month!r}")
    y, m = int(y_s), int(m_s)
    if not 1 <= m <= 12:
        raise ValueError(f"month の月が不正です: {month!r}")
    return f"{y:04d}-{m:02d}"


def _extract_target(kind: str, entry: dict) -> tuple[date | None, str | None, str | None]:
    """entry から対象期間キー（target_date / target_month / target_period）を決定的に取り出す。

    欠落は ValueError（fail-loud＝アーカイブの同一性キーを黙って空にしない）。
    """
    if kind == "diary":
        raw = str(entry.get("date") or "").strip()
        if not raw:
            raise ValueError("日誌 entry に date（記録日）がありません")
        return date.fromisoformat(raw), None, None
    if kind in ("monthly", "class_monthly"):
        month = str(entry.get("month") or "").strip()
        if not month:
            raise ValueError(f"{kind} entry に month（対象月）がありません")
        # ゼロ詰め正規化＝"2026-7" を "2026-07" に揃える（辞書順比較・dedupe_key の前提を守る）。
        return None, normalize_month(month), None
    if kind == "child_record":
        period = str(entry.get("period") or "").strip()
        if not period:
            raise ValueError("保育経過記録 entry に period（対象期間）がありません")
        return None, None, period
    if kind == "nursery_record":
        # 要録は年度が対象期間（例 "2026"）。target_period 列に格納して同一性キーに使う（§19・L4）。
        fiscal_year = str(entry.get("fiscal_year") or "").strip()
        if not fiscal_year:
            raise ValueError("保育要録 entry に fiscal_year（対象年度）がありません")
        return None, None, fiscal_year
    raise ValueError(f"kind は {DOC_KINDS} のいずれか: {kind!r}")


def _extract_child_display(kind: str, entry: dict) -> str:
    """書類の主対象の子ども表示名（日誌・クラス月案はクラス単位なので空）。"""
    if kind in ("diary", "class_monthly"):
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
    elif kind == "class_monthly":
        # クラス月案は 0–2 の個人目標小表に登場児が並ぶ（クラス単位なので主対象児は無い）。
        for goal in entry.get("individual_goals") or []:
            name = str((goal or {}).get("child_id") or "").strip()
            if name and name not in names:
                names.append(name)
    return names


def _dedupe_key(kind: str, child_display: str, entry: dict) -> str:
    d, m, p = _extract_target(kind, entry)
    target = d.isoformat() if d else (m or p or "")
    key = f"{kind}|{child_display}|{target}"
    # クラス単位の書類（主対象児なし＝日誌/クラス月案）はクラス（v0＝年齢帯）も同一性に含める。
    # 含めないと同日・別クラスの日誌／同月・別クラスのクラス月案が同一書類に潰れて版が混線する。
    if kind in ("diary", "class_monthly"):
        key += f"|{str(entry.get('age_band') or '')}"
    return key


def _workspace_uuid(workspace_id: str | uuid.UUID | None) -> uuid.UUID:
    """呼出境界の workspace_id を UUID に正規化する（未指定はローカル開発用の固定領域）。"""
    if workspace_id is None or workspace_id == "":
        return LOCAL_WORKSPACE_ID
    return workspace_id if isinstance(workspace_id, uuid.UUID) else uuid.UUID(str(workspace_id))


def _ensure_workspace(session: Session, workspace_id: uuid.UUID, now: datetime) -> None:
    """開発用固定領域を含め、参照先 workspace を存在させる（FK と create_all テストの両立）。"""
    if session.get(Workspace, workspace_id) is None:
        session.add(
            Workspace(
                id=workspace_id,
                name="ローカル開発" if workspace_id == LOCAL_WORKSPACE_ID else "マイワークスペース",
                created_at=now,
                updated_at=now,
            )
        )
        session.flush()


def _resolve_child(
    session: Session, display_name: str, workspace_id: uuid.UUID, now: datetime
) -> Child:
    """表示名→児童マスタ行（無ければ auto-create）。名前→UUID 解決の唯一の境界。"""
    child = session.scalar(
        sa.select(Child).where(
            Child.workspace_id == workspace_id, Child.display_name == display_name
        )
    )
    if child is None:
        child = Child(
            workspace_id=workspace_id, display_name=display_name, created_at=now, updated_at=now
        )
        session.add(child)
        session.flush()
    return child


def _find_document(
    session: Session, kind: str, entry: dict, workspace_id: uuid.UUID
) -> DocumentRecord | None:
    key = _dedupe_key(kind, _extract_child_display(kind, entry), entry)
    return session.scalar(
        sa.select(DocumentRecord).where(
            DocumentRecord.workspace_id == workspace_id, DocumentRecord.dedupe_key == key
        )
    )


# ──────────────────────────── 書込 API（web から中継・actor/now は外部注入） ────────────────────────────


def save_document(
    kind: str,
    entry: dict,
    rendered_text: str = "",
    *,
    author_kind: str = "ai",
    actor: str = "",
    workspace_id: str | uuid.UUID | None = None,
    now: datetime,
) -> dict:
    """確定書類を保存する（同一書類は版を積む upsert）。

    - 同一性は dedupe_key（doc_type × 子ども表示名 × 対象期間）。既存なら新しい版（seq+1）を追加し
      current_version を進める。承認済み（approved）の書類も編集保存で版は積める（証跡が残る）。
    - author_kind="ai"（AI 確定）→ audit action=finalize / "caregiver"（編集保存）→ action=edit /
      "imported"（外部ファイルの取込保存＝アップロード）→ action=import。
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
    actor = _clamp_actor(actor)  # created_by / AuditEvent.actor は VARCHAR(100)
    try:
        target_date, target_month, target_period = _extract_target(kind, entry)
        child_display = _extract_child_display(kind, entry)
        key = _dedupe_key(kind, child_display, entry)
        workspace = _workspace_uuid(workspace_id)
        with Session(eng) as session, session.begin():
            _ensure_workspace(session, workspace, now)
            for name in _mentioned_children(kind, entry):
                _resolve_child(session, name, workspace, now)
            doc = session.scalar(
                sa.select(DocumentRecord).where(
                    DocumentRecord.workspace_id == workspace, DocumentRecord.dedupe_key == key
                )
            )
            if doc is None:
                doc = DocumentRecord(
                    workspace_id=workspace,
                    doc_type=kind,
                    dedupe_key=key,
                    child_id=(
                        _resolve_child(session, child_display, workspace, now).id
                        if child_display
                        else None
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
            # 承認後に新しい版が積まれたら承認は失効させる（現行版＝未承認の finalized へ戻す）。旧内容への
            # 承認証跡は audit に残るが、編集後の現行内容を「承認済み」と偽らない（§偽の緑を出さない）。
            # 書類管理タブでの編集（caregiver）は編集→再承認の流れに乗る（decision A）。
            if doc.status == "approved":
                doc.status = "finalized"
            session.add(
                AuditEvent(
                    document_id=doc.id,
                    actor=actor,
                    action=_AUTHOR_KIND_ACTION[author_kind],
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
        return _write_error(e)


def touch_user(email: str, *, google_subject: str = "", now: datetime) -> dict:
    """検証済み Google ユーザーを users へ auto-provision し、表示用情報を返す（Phase 3）。

    children と同じ流儀＝初回アクセス時に行を作る（登録画面を待たせない）。display_name は
    後から DB で設定でき、設定済みなら actor 表示に使える。降格・障害・空 email は
    {"status": "skipped"/"error"}（本流＝書類の保存・承認を壊さない）。
    """
    email = email.strip()
    subject = google_subject.strip()
    eng = _engine()
    if eng is None or not email:
        return {"status": "skipped"}
    try:
        with Session(eng) as session, session.begin():
            user = (
                session.scalar(sa.select(User).where(User.google_subject == subject))
                if subject
                else None
            )
            if user is None:
                user = session.scalar(sa.select(User).where(User.email == email))
            if user is None:
                workspace = Workspace(name=email[:100], created_at=now, updated_at=now)
                session.add(workspace)
                session.flush()
                user = User(
                    email=email,
                    google_subject=subject or None,
                    workspace_id=workspace.id,
                    created_at=now,
                    updated_at=now,
                )
                session.add(user)
                session.flush()
            elif subject and user.google_subject not in (None, subject):
                # email が再利用・取り違えられても別 Google アカウントへ既存表示名を渡さない。
                return {"status": "error", "detail": "Google アカウントの対応付けが一致しません"}
            elif subject:
                user.google_subject = subject
                # Google の確認済み email は変更され得る。subject が同じ行だけ更新する。
                user.email = email
                user.updated_at = now
            if user.workspace_id is None:
                # 旧 users 行には既存書類を自動付与しない。Google subject と既存データの対応を推測すると、
                # 他人のデータを見せる事故になるため、新しい個人領域から開始する。
                workspace = Workspace(name=email[:100], created_at=now, updated_at=now)
                session.add(workspace)
                session.flush()
                user.workspace_id = workspace.id
            return {
                "status": "ok",
                "email": user.email,
                "display_name": user.display_name,
                "active": user.active,
                "workspace_id": str(user.workspace_id),
            }
    except SQLAlchemyError as e:
        return _write_error(e)


def set_user_display_name(
    email: str, display_name: str, *, google_subject: str = "", now: datetime
) -> dict:
    """検証済み Google ユーザーの display_name を設定する（Phase 3＝自分の表示名の登録/編集）。

    `touch_user` と同じ upsert（無ければ作成）で display_name を更新する。設定済みなら
    `_resolve_actor` が監査証跡を「表示名（email）」で残す（表示名を消費する仕組みは既存）。
    email と subject は呼び出し元（web/routes）が **Google の検証済み値**を渡す＝偽装不可（body 由来を使わない）。
    空 email/未接続は {"status": "skipped"}、DB 障害は {"status": "error"}（本流を壊さない既存流儀）。
    display_name は列上限（100）に clamp。空文字は表示名クリア（actor は email へ戻る）を許す。
    """
    email = email.strip()
    name = display_name.strip()[:100]
    subject = google_subject.strip()
    eng = _engine()
    if eng is None or not email:
        return {"status": "skipped"}
    try:
        with Session(eng) as session, session.begin():
            user = (
                session.scalar(sa.select(User).where(User.google_subject == subject))
                if subject
                else None
            )
            if user is None:
                user = session.scalar(sa.select(User).where(User.email == email))
            if user is None:
                workspace = Workspace(name=email[:100], created_at=now, updated_at=now)
                session.add(workspace)
                session.flush()
                user = User(
                    email=email,
                    google_subject=subject or None,
                    workspace_id=workspace.id,
                    created_at=now,
                    updated_at=now,
                )
                session.add(user)
            elif subject and user.google_subject not in (None, subject):
                return {"status": "error", "detail": "Google アカウントの対応付けが一致しません"}
            elif subject:
                user.google_subject = subject
                user.email = email
            user.display_name = name
            user.updated_at = now
            if user.workspace_id is None:
                workspace = Workspace(name=email[:100], created_at=now, updated_at=now)
                session.add(workspace)
                session.flush()
                user.workspace_id = workspace.id
            session.flush()
            return {
                "status": "ok",
                "email": user.email,
                "display_name": user.display_name,
                "active": user.active,
                "workspace_id": str(user.workspace_id),
            }
    except SQLAlchemyError as e:
        return _write_error(e)


def request_workspace_deletion(
    email: str, *, google_subject: str, now: datetime, retention_days: int = 30
) -> dict:
    """検証済み本人からの削除依頼を受け付ける（即時消去ではなく30日後の実行待ち）。

    session/email の自己申告は使わず、routes が Google ID token 検証済みの subject を渡す。既に未処理の
    依頼があれば重複作成せず同じ受付情報を返すため、二重クリックも安全である。
    """
    email = email.strip()
    subject = google_subject.strip()
    eng = _engine()
    if eng is None or not email or not subject:
        return {"status": "skipped"}
    # 削除画面を最初に開いた直後でも受け付けられるよう、identity 行はこの境界で確実に作る。
    provisioned = touch_user(email, google_subject=subject, now=now)
    if provisioned.get("status") != "ok":
        return provisioned
    try:
        with Session(eng) as session, session.begin():
            user = session.scalar(sa.select(User).where(User.google_subject == subject))
            if user is None or user.workspace_id is None:
                return {"status": "error", "detail": "アカウント情報を確認できません"}
            pending = session.scalar(
                sa.select(DeletionRequest).where(
                    DeletionRequest.user_id == user.id,
                    DeletionRequest.status == "pending",
                )
            )
            if pending is None:
                pending = DeletionRequest(
                    workspace_id=user.workspace_id,
                    user_id=user.id,
                    email=user.email,
                    status="pending",
                    requested_at=now,
                    due_at=now + timedelta(days=retention_days),
                )
                session.add(pending)
                session.flush()
            return {
                "status": "pending",
                "request_id": str(pending.id),
                "due_at": pending.due_at.isoformat(),
            }
    except SQLAlchemyError as e:
        return _write_error(e)


def process_due_deletion_requests(*, now: datetime) -> dict:
    """期限を過ぎた削除依頼の workspace を不可逆に消去する管理用処理。

    Web からは呼ばない。運営者が定期ジョブまたは管理端末のスクリプトから実行する。documents を起点に
    版・監査・フィードバックを先に消し、最後に users/workspace を削除して、個人情報を残さない。
    """
    eng = _engine()
    if eng is None:
        return {"status": "skipped", "processed": 0}
    try:
        with Session(eng) as session, session.begin():
            requests = list(
                session.scalars(
                    sa.select(DeletionRequest).where(
                        DeletionRequest.status == "pending", DeletionRequest.due_at <= now
                    )
                )
            )
            for req in requests:
                workspace = req.workspace_id
                document_ids = sa.select(DocumentRecord.id).where(
                    DocumentRecord.workspace_id == workspace
                )
                session.execute(sa.delete(Feedback).where(Feedback.workspace_id == workspace))
                session.execute(
                    sa.delete(AuditEvent).where(AuditEvent.document_id.in_(document_ids))
                )
                session.execute(
                    sa.delete(DocumentVersion).where(DocumentVersion.document_id.in_(document_ids))
                )
                session.execute(
                    sa.delete(DocumentRecord).where(DocumentRecord.workspace_id == workspace)
                )
                session.execute(sa.delete(Child).where(Child.workspace_id == workspace))
                session.execute(sa.delete(Class).where(Class.workspace_id == workspace))
                # policy/notation は JSON ブック1行。workspaces 導入前のテーブルなので key で同じ境界を
                # 表現している（routes と同じ命名）。SQLAlchemy ORM を重ねず生テーブルで消す。
                inspector = sa.inspect(session.bind)
                if inspector.has_table("policy_books"):
                    session.execute(
                        sa.text("DELETE FROM policy_books WHERE id = :id"),
                        {"id": f"workspace:{workspace}"},
                    )
                if inspector.has_table("notation_books"):
                    session.execute(
                        sa.text("DELETE FROM notation_books WHERE id = :id"),
                        {"id": f"workspace:{workspace}"},
                    )
                session.execute(
                    sa.delete(DeletionRequest).where(DeletionRequest.workspace_id == workspace)
                )
                session.execute(sa.delete(User).where(User.workspace_id == workspace))
                session.execute(sa.delete(Workspace).where(Workspace.id == workspace))
            return {"status": "ok", "processed": len(requests)}
    except SQLAlchemyError as e:
        return _write_error(e)


def upsert_child(
    display_name: str,
    *,
    family_name: str | None = None,
    given_name: str | None = None,
    gender: str | None = None,
    birthdate: date | None = None,
    workspace_id: str | uuid.UUID | None = None,
    now: datetime,
) -> dict:
    """児童マスタへ表示名で upsert する（無ければ作成・本名/性別/誕生日を補完）。冪等。

    表示名→children.id 解決の唯一の境界（`_resolve_child`）を共有する。「書類を作る」の新規児登録
    （呼び名＋敬称＝display_name はフロントが `compose_display_name` で組む）や園名簿の事前登録に使う。
    本名（family_name/given_name）は氏名欄用で **DB のみ・repo/eval には持ち込まない**（§14）。
    既存行の非空フィールドは上書きしない（保育士が後から整えた値を壊さない）＝未設定のときだけ補完
    する（birthdate と同じ流儀）。降格・空名は skipped。
    """
    display_name = display_name.strip()
    eng = _engine()
    if eng is None or not display_name:
        return {"status": "skipped"}
    try:
        workspace = _workspace_uuid(workspace_id)
        with Session(eng) as session, session.begin():
            _ensure_workspace(session, workspace, now)
            existing = session.scalar(
                sa.select(Child).where(
                    Child.workspace_id == workspace, Child.display_name == display_name
                )
            )
            created = existing is None
            child = _resolve_child(session, display_name, workspace, now)
            touched = False
            if birthdate is not None and child.birthdate is None:
                child.birthdate = birthdate
                touched = True
            if family_name and family_name.strip() and not (child.family_name or ""):
                child.family_name = family_name.strip()
                touched = True
            if given_name and given_name.strip() and not (child.given_name or ""):
                child.given_name = given_name.strip()
                touched = True
            if gender and gender.strip() and not (child.gender or ""):
                child.gender = gender.strip()
                touched = True
            if touched:
                child.updated_at = now
            return {"status": "created" if created else "exists", **_child_view(child)}
    except SQLAlchemyError as e:
        return _write_error(e)


def upsert_class(
    name: str, fiscal_year: str = "", *, workspace_id: str | uuid.UUID | None = None, now: datetime
) -> dict:
    """クラス（組）を (name, fiscal_year) で upsert する（無ければ作成）。冪等。

    園の名簿管理でクラスを定義する口（web `/api/classes` の中継先）。同一性は組名＋年度＝進級で
    組名が再利用されても年度で分かれる。年齢帯は在籍児の生年月日から導出するため、ここでは保存しない。
    空名・未接続は skipped、DB 障害は error。
    """
    name = name.strip()
    fiscal_year = fiscal_year.strip()
    eng = _engine()
    if eng is None or not name:
        return {"status": "skipped"}
    try:
        workspace = _workspace_uuid(workspace_id)
        with Session(eng) as session, session.begin():
            _ensure_workspace(session, workspace, now)
            existing = session.scalar(
                sa.select(Class).where(
                    Class.workspace_id == workspace,
                    Class.name == name,
                    Class.fiscal_year == fiscal_year,
                )
            )
            created = existing is None
            if existing is None:
                cls = Class(
                    workspace_id=workspace,
                    name=name,
                    fiscal_year=fiscal_year,
                    created_at=now,
                    updated_at=now,
                )
                session.add(cls)
                session.flush()
            else:
                cls = existing
            return {"status": "created" if created else "exists", **_class_view(cls)}
    except SQLAlchemyError as e:
        return _write_error(e)


def assign_child_to_class(
    child_display_name: str,
    class_id: str | None,
    *,
    workspace_id: str | uuid.UUID | None = None,
    now: datetime,
) -> dict:
    """児童を指定クラスへ割り当てる（class_id=None/"" で未所属へ戻す）。

    表示名→children 行を解決し class_id を張り替える（園の名簿管理での割当/移動/解除）。児童が
    未登録・クラスが不在は error（先に登録する）。空名・未接続は skipped、不正 id・DB 障害は error。
    """
    name = child_display_name.strip()
    eng = _engine()
    if eng is None or not name:
        return {"status": "skipped"}
    raw = (class_id or "").strip()
    try:
        target_uuid = uuid.UUID(raw) if raw else None
    except ValueError:
        return {"status": "error", "detail": f"class_id が不正です: {class_id!r}"}
    try:
        workspace = _workspace_uuid(workspace_id)
        with Session(eng) as session, session.begin():
            child = session.scalar(
                sa.select(Child).where(Child.workspace_id == workspace, Child.display_name == name)
            )
            if child is None:
                return {"status": "error", "detail": "対象の児童がいません（先に登録してください）"}
            cls = None
            if target_uuid is not None:
                cls = session.scalar(
                    sa.select(Class).where(Class.id == target_uuid, Class.workspace_id == workspace)
                )
                if cls is None:
                    return {"status": "error", "detail": "対象のクラスがありません"}
            child.class_id = target_uuid
            child.updated_at = now
            session.flush()
            return {"status": "ok", **_child_view(child, cls)}
    except SQLAlchemyError as e:
        return _write_error(e)


def get_child(display_name: str, *, workspace_id: str | uuid.UUID | None = None) -> dict | None:
    """表示名→児童マスタの本名/性別/誕生日（氏名欄の本名解決に使う＝帳票PDF）。未接続/不在は None。"""
    name = display_name.strip()
    eng = _engine()
    if eng is None or not name:
        return None
    try:
        workspace = _workspace_uuid(workspace_id)
        with Session(eng) as session:
            child = session.scalar(
                sa.select(Child).where(Child.workspace_id == workspace, Child.display_name == name)
            )
            return _child_view(child) if child else None
    except SQLAlchemyError:
        return None


def approve_document(
    kind: str,
    entry: dict,
    *,
    actor: str,
    workspace_id: str | uuid.UUID | None = None,
    now: datetime,
    expected_version_seq: int | None = None,
    memory_synced_version_id: str | uuid.UUID | None = None,
    memory_status: str = "skipped",
) -> dict:
    """書類を承認済み（approved）にし、証跡（audit action=approve）を残す。

    対象は dedupe_key で特定する（未保存なら error＝先に save_document）。

    承認は「保育士が画面で見ていた版」に対する意思なので、`expected_version_seq` を渡すと現行版の seq と
    突合し、不一致なら error を返す（並行編集で別の未レビュー版が積まれた後の取り違えを防ぐ＝編集→承認の
    競合。逆方向の承認→編集は save_document の demote で守られている）。省略時は従来どおり現行版を承認する。
    証跡（AuditEvent.detail）には承認した version_seq を必ず記録する（save_document と対称＝「どの版を
    承認したか」を後から復元できる）。
    """
    eng = _engine()
    if eng is None:
        return {"status": "skipped", "reason": "DATABASE_URL 未設定（アーカイブ降格）"}
    actor = _clamp_actor(actor)  # AuditEvent.actor は VARCHAR(100)
    try:
        workspace = _workspace_uuid(workspace_id)
        with Session(eng) as session, session.begin():
            doc = _find_document(session, kind, entry, workspace)
            if doc is None:
                return {"status": "error", "detail": "対象の書類がアーカイブにありません（未保存）"}
            current_seq = 0
            if doc.current_version_id is not None:
                version = session.get(DocumentVersion, doc.current_version_id)
                current_seq = version.seq if version else 0
            if expected_version_seq is not None and expected_version_seq != current_seq:
                return {
                    "status": "error",
                    "code": "version_conflict",
                    "detail": (
                        "先に別の編集が保存されています。最新の内容を読み込んでから承認してください。"
                    ),
                    "current_version_seq": current_seq,
                }
            expected_memory_version = (
                uuid.UUID(str(memory_synced_version_id)) if memory_synced_version_id else None
            )
            if (
                expected_memory_version is not None
                and expected_memory_version != doc.current_version_id
            ):
                return {
                    "status": "error",
                    "code": "version_conflict",
                    "detail": "Memory Bankへ同期した版と現在の版が一致しません。再度確認してください。",
                    "current_version_seq": current_seq,
                }
            if doc.status == "approved" and (
                expected_memory_version is None
                or doc.memory_synced_version_id == expected_memory_version
            ):
                return {
                    "status": "approved",
                    "document_id": str(doc.id),
                    "version_seq": current_seq,
                    "memory_status": (
                        "already_synced"
                        if doc.memory_synced_version_id == doc.current_version_id
                        else memory_status
                    ),
                }
            doc.status = "approved"
            doc.updated_at = now
            if expected_memory_version is not None:
                doc.memory_synced_version_id = expected_memory_version
                doc.memory_synced_at = now
            session.add(
                AuditEvent(
                    document_id=doc.id,
                    actor=actor,
                    action="approve",
                    detail={"version_seq": current_seq, "memory_status": memory_status},
                    at=now,
                )
            )
            return {
                "status": "approved",
                "document_id": str(doc.id),
                "version_seq": current_seq,
                "memory_status": memory_status,
            }
    except (ValueError, SQLAlchemyError) as e:
        return _write_error(e)


def get_approval_candidate(
    kind: str,
    entry: dict,
    *,
    workspace_id: str | uuid.UUID | None = None,
    expected_version_seq: int | None = None,
) -> dict:
    """承認対象の保存済み現行版を返す（Memory Bank同期前の権威的な読み取り）。

    リクエスト本文は書類のdedupe特定にだけ使い、Memory Bankへ渡す本文はDBの現行版から取得する。
    これにより、未保存の改変内容や別版を承認・記憶する競合を防ぐ。
    """
    eng = _engine()
    if eng is None:
        return {"status": "skipped", "reason": "DATABASE_URL 未設定（アーカイブ降格）"}
    try:
        workspace = _workspace_uuid(workspace_id)
        with Session(eng) as session:
            doc = _find_document(session, kind, entry, workspace)
            if doc is None or doc.current_version_id is None:
                return {"status": "error", "detail": "対象の書類がアーカイブにありません（未保存）"}
            version = session.get(DocumentVersion, doc.current_version_id)
            if version is None:
                return {"status": "error", "detail": "承認対象の現行版を取得できません"}
            if expected_version_seq is not None and expected_version_seq != version.seq:
                return {
                    "status": "error",
                    "code": "version_conflict",
                    "detail": "先に別の編集が保存されています。最新の内容を確認してください。",
                    "current_version_seq": version.seq,
                }
            return {
                "status": "ready",
                "document_id": str(doc.id),
                "version_id": str(version.id),
                "version_seq": version.seq,
                "entry": version.entry,
                "rendered_text": version.rendered_text,
                "already_approved": doc.status == "approved",
                "memory_synced": doc.memory_synced_version_id == version.id,
            }
    except (ValueError, SQLAlchemyError) as e:
        return _write_error(e)


def save_feedback(
    document_id: str,
    verdict: str,
    comment: str = "",
    *,
    actor: str = "",
    workspace_id: str | uuid.UUID | None = None,
    now: datetime,
) -> dict:
    """書類への 👍👎（＋ひとこと）を、その文書と**現行版**に紐付けて保存する（§8「回す」の一次入力）。

    - 対象は document_id（確定画面／「書類を見る」タブが持つ書類 id）。版は保存時点の
      `current_version_id` をサーバ側で解決して埋める（「どの版への評価か」を固定＝frontend に版 id を
      扱わせない）。verdict は up/down のみ（それ以外は error）。comment（ひとこと）は任意。
    - 降格：`DATABASE_URL` 未設定は {"status": "skipped"}（フィードバックは保存の本流ではない補助シグナル
      なので、未接続でも改善フロー自体は別途動く）。不正 id/対象不在/DB 障害は {"status": "error"}。

    Returns:
        {"status": "saved", "feedback_id", "document_id", "version_seq"} ／
        {"status": "skipped"} ／ {"status": "error", "detail"}
    """
    eng = _engine()
    if eng is None:
        return {"status": "skipped", "reason": "DATABASE_URL 未設定（フィードバック降格）"}
    actor = _clamp_actor(actor)  # Feedback.actor は VARCHAR(100)
    v = (verdict or "").strip()
    if v not in FEEDBACK_VERDICTS:
        return {
            "status": "error",
            "detail": f"verdict は {FEEDBACK_VERDICTS} のいずれか: {verdict!r}",
        }
    try:
        doc_uuid = uuid.UUID(document_id)
    except (ValueError, TypeError):
        return {"status": "error", "detail": f"document_id が不正です: {document_id!r}"}
    try:
        workspace = _workspace_uuid(workspace_id)
        with Session(eng) as session, session.begin():
            doc = session.scalar(
                sa.select(DocumentRecord).where(
                    DocumentRecord.id == doc_uuid, DocumentRecord.workspace_id == workspace
                )
            )
            if doc is None:
                return {"status": "error", "detail": "対象の書類がアーカイブにありません"}
            version_seq = 0
            if doc.current_version_id is not None:
                version = session.get(DocumentVersion, doc.current_version_id)
                version_seq = version.seq if version else 0
            fb = Feedback(
                workspace_id=workspace,
                document_id=doc.id,
                version_id=doc.current_version_id,
                verdict=v,
                comment=(comment or "").strip(),
                actor=actor,
                created_at=now,
            )
            session.add(fb)
            session.flush()
            return {
                "status": "saved",
                "feedback_id": str(fb.id),
                "document_id": str(doc.id),
                "version_seq": version_seq,
            }
    except (ValueError, SQLAlchemyError) as e:
        return _write_error(e)


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
        "memory_synced": doc.memory_synced_version_id == doc.current_version_id,
        "updated_at": doc.updated_at.isoformat(),
    }


def list_documents(
    doc_type: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = 200,
    workspace_id: str | uuid.UUID | None = None,
) -> list[dict]:
    """書類メタの一覧（新しい順）。降格・障害は空（読取は落とさない＝policy_store の read と同じ）。"""
    eng = _engine()
    if eng is None:
        return []
    try:
        workspace = _workspace_uuid(workspace_id)
        with Session(eng) as session:
            q = (
                sa.select(DocumentRecord)
                .where(DocumentRecord.workspace_id == workspace)
                .order_by(DocumentRecord.updated_at.desc())
                .limit(limit)
            )
            if doc_type:
                q = q.where(DocumentRecord.doc_type == doc_type)
            if date_from:
                q = q.where(DocumentRecord.target_date >= date_from)
            if date_to:
                q = q.where(DocumentRecord.target_date <= date_to)
            docs = list(session.scalars(q))
            names = {
                c.id: c.display_name
                for c in session.scalars(sa.select(Child).where(Child.workspace_id == workspace))
            }
            return [_doc_view(d, names.get(d.child_id)) for d in docs]
    except SQLAlchemyError:
        return []


def get_document(document_id: str, *, workspace_id: str | uuid.UUID | None = None) -> dict | None:
    """単一書類の全文（メタ＋現行版の本文 entry・整形テキスト・確定/編集の区別・担当者）を返す。

    「作成済み書類を見る」タブ（アーカイブ閲覧＝参照データの点検）用。整形テキストは画面表示に、
    entry は帳票PDF 出力に使う（どちらも現行版＝最新の内容）。版履歴の全展開・監査証跡はここでは
    返さない（閲覧の主眼は確定内容そのもの）。未接続・不正 id・不在・障害は None（読取は落とさない）。
    """
    eng = _engine()
    if eng is None:
        return None
    try:
        doc_uuid = uuid.UUID(document_id)
    except ValueError:
        return None
    try:
        workspace = _workspace_uuid(workspace_id)
        with Session(eng) as session:
            doc = session.scalar(
                sa.select(DocumentRecord).where(
                    DocumentRecord.id == doc_uuid, DocumentRecord.workspace_id == workspace
                )
            )
            if doc is None:
                return None
            child_display = None
            if doc.child_id is not None:
                child = session.get(Child, doc.child_id)
                child_display = child.display_name if child else None
            version = (
                session.get(DocumentVersion, doc.current_version_id)
                if doc.current_version_id is not None
                else None
            )
            view = _doc_view(doc, child_display)
            view["entry"] = version.entry if version else {}
            view["rendered_text"] = version.rendered_text if version else ""
            view["author_kind"] = version.author_kind if version else ""
            view["created_by"] = version.created_by if version else ""
            view["version_seq"] = version.seq if version else 0
            return view
    except SQLAlchemyError:
        return None


def list_diary_entries(
    date_from: date,
    date_to: date,
    *,
    approved_only: bool = False,
    workspace_id: str | uuid.UUID | None = None,
) -> list[dict]:
    """期間内の日誌の最新版 entry（JSON）を日付順に返す＝月案 L2／保育経過記録 L3 の seed 取得元。

    集計そのもの（child_id 別の decomposition）は fetch_reference が呼ぶ harness/reference・aggregate が
    担う＝ここは「期間の日誌本文を引く」だけ（責務を重ねない）。
    """
    eng = _engine()
    if eng is None:
        return []
    try:
        workspace = _workspace_uuid(workspace_id)
        with Session(eng) as session:
            q = (
                sa.select(DocumentRecord)
                .where(
                    DocumentRecord.workspace_id == workspace,
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


def _diary_evaluation_complete(entry: dict) -> bool:
    """日誌 entry の評価・反省（2視点）が両方記入済みか（validate_fields の「2視点必須」と同じ判定）。

    (a)子どもに焦点／(b)自分の保育の適否のどちらかでも空なら未完＝未記入とみなす（クラス月案作成時に
    「前月日誌の評価が未記入なら記入を促す」動線の判定に使う）。entry は現行版の本文 JSON。壊れ/欠落は
    未記入扱い（安全側）。判定ルールはここに1つ（frontend で再実装しない＝ドリフト防止）。
    """
    ev = (entry or {}).get("evaluation") or {}
    return bool(str(ev.get("child_focus") or "").strip()) and bool(
        str(ev.get("self_review") or "").strip()
    )


def list_diary_meta(
    date_from: date, date_to: date, *, workspace_id: str | uuid.UUID | None = None
) -> list[dict]:
    """期間内の日誌メタ（id・対象日・状態・評価充足）を日付順に返す＝クラス月案作成時の未記入検出用。

    本文（entry）は載せない軽量メタ（充足判定だけ済ませて返す＝ワイヤは軽い）。seed 取得
    （list_diary_entries＝本文が要る）とは役割が別。id はフロントが「その日誌へ飛んで編集」する導線に使う。
    降格・障害は空（読取は落とさない＝list_diary_entries と同じ）。
    """
    eng = _engine()
    if eng is None:
        return []
    try:
        workspace = _workspace_uuid(workspace_id)
        with Session(eng) as session:
            q = (
                sa.select(DocumentRecord)
                .where(
                    DocumentRecord.workspace_id == workspace,
                    DocumentRecord.doc_type == "diary",
                    DocumentRecord.target_date >= date_from,
                    DocumentRecord.target_date <= date_to,
                )
                .order_by(DocumentRecord.target_date)
            )
            rows: list[dict] = []
            for doc in session.scalars(q):
                version = session.scalar(
                    sa.select(DocumentVersion).where(DocumentVersion.id == doc.current_version_id)
                )
                entry = version.entry if version is not None else {}
                rows.append(
                    {
                        "id": str(doc.id),
                        "date": doc.target_date.isoformat() if doc.target_date else "",
                        "status": doc.status,
                        # クラス月案は年齢帯（クラス）単位なので、フロントが当該クラスの日誌だけに絞れるよう返す。
                        "age_band": (entry or {}).get("age_band") or "",
                        "evaluation_complete": _diary_evaluation_complete(entry),
                    }
                )
            return rows
    except SQLAlchemyError:
        return []


def list_child_record_entries(
    child_display_name: str,
    *,
    exclude_period: str | None = None,
    workspace_id: str | uuid.UUID | None = None,
) -> list[dict]:
    """指定児の保育経過記録の最新版 entry（JSON）を期間順に返す＝要録 L4 seed・保育経過記録の
    「前回まで」seed・年間マトリクス帳票の過去期埋め込みの取得元。

    **全期（年度跨ぎ含む）を返す**（依存モデル＝「それまでの作成済み過去のものすべて」）。
    `exclude_period` を与えると当該期間の記録を除く（＝今期の保育経過記録を作り直すとき、作成対象の
    期そのものを「前回まで」に混ぜない）。どの期をどの列に置くか（年度の同定・期→列の割当）は
    帳票描画側（web/chohyo_pdf）の責務で、ここは「引く」だけ（責務を重ねない）。降格・障害・該当なしは空。
    """
    name = child_display_name.strip()
    eng = _engine()
    if eng is None or not name:
        return []
    try:
        workspace = _workspace_uuid(workspace_id)
        with Session(eng) as session:
            child = session.scalar(
                sa.select(Child).where(Child.workspace_id == workspace, Child.display_name == name)
            )
            if child is None:
                return []
            q = (
                sa.select(DocumentRecord)
                .where(
                    DocumentRecord.workspace_id == workspace,
                    DocumentRecord.doc_type == "child_record",
                    DocumentRecord.child_id == child.id,
                )
                .order_by(DocumentRecord.target_period)
            )
            if exclude_period is not None and exclude_period.strip():
                q = q.where(DocumentRecord.target_period != exclude_period.strip())
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


def _roster_children(
    session: Session, workspace: uuid.UUID, age_band: str, reference_date: date
) -> list[tuple[Child, Class]]:
    """対象年度のクラスに在籍し、生年月日から導出した年齢帯が一致する児童（名簿の決定実体・表示名順）。

    「クラス（年齢帯）の在籍児」の同定はここに1つ＝クラス月案 seed（`list_class_child_record_entries`）と
    在籍児名簿（`class_roster`）が共用する。クラスは年齢帯を保存しないため、対象年度の4月1日
    （`reference_date`）時点の満年齢で分類する。生年月日未登録の児は年齢帯を推測せず含めない。
    """
    return [
        (child, cls)
        for child, cls in session.execute(
            sa.select(Child, Class)
            .join(Class, Child.class_id == Class.id)
            .where(
                Class.workspace_id == workspace,
                Child.workspace_id == workspace,
                Class.active.is_(True),
                Child.active.is_(True),
            )
            .order_by(Child.display_name)
        )
        if (not cls.fiscal_year or cls.fiscal_year == str(reference_date.year))
        and age_band_for_birthdate(child.birthdate, reference_date) == age_band
    ]


def class_roster(
    age_band: str, month: str, *, workspace_id: str | uuid.UUID | None = None
) -> list[dict]:
    """クラス（年齢帯）の在籍児名簿＝クラス月案の与件（クラス・園児マスタから決定的に引く）。

    0–2 の個人目標を「過去記録に登場した子」でなく**名簿の在籍児**を基準に書けるようにする
    （記録がまだ1件も無い新入園児を落とさない・§18）。在籍児の同定は seed と同じ
    `_roster_children`（対象年度4月1日時点の年齢帯分類）。月齢ラベルは対象月の1日時点で計算する
    （個人目標 `age_months` の素）。名簿未整備・DB 未接続・該当なしは空を返し、fetch_reference が
    「名簿なし」を author へ正直に降格メッセージ化する。month 不正は ValueError（呼び出し側が降格/400）。
    """
    if age_band not in AGE_BANDS:
        return []
    month = normalize_month(month)
    reference_date = fiscal_year_start(month)
    age_as_of = date(int(month[:4]), int(month[5:7]), 1)
    eng = _engine()
    if eng is None:
        return []
    try:
        workspace = _workspace_uuid(workspace_id)
        with Session(eng) as session:
            return [
                {
                    "child_id": child.display_name,
                    "age_months": (
                        age_months_label(child.birthdate, age_as_of) if child.birthdate else ""
                    ),
                    "class_name": cls.name,
                }
                for child, cls in _roster_children(session, workspace, age_band, reference_date)
            ]
    except SQLAlchemyError:
        return []


def list_class_child_record_entries(
    age_band: str,
    *,
    as_of: date | None = None,
    workspace_id: str | uuid.UUID | None = None,
) -> list[dict]:
    """クラス（年齢帯）の児童の保育経過記録の最新版 entry を（児童・期間順に）返す＝クラス月案 seed。

    「クラスの児童」の同定は**名簿（Class＝組マスタ）優先**：対象年度の4月1日時点で、在籍児の
    生年月日から導出した年齢帯が一致する児童の保育経過記録を**全期（年度跨ぎ含む）**引く。クラスは
    年齢帯を保存しない。名簿未整備・生年月日未登録なら entry の age_band 一致で降格フィルタする。
    降格・障害・該当なしは空。
    """
    if age_band not in AGE_BANDS:
        return []
    reference_date = as_of or fiscal_year_start_for_year("")
    eng = _engine()
    if eng is None:
        return []
    try:
        workspace = _workspace_uuid(workspace_id)
        with Session(eng) as session:
            # 名簿優先：当該年度のクラスに在籍する児童を、生年月日から年齢帯へ分類する。
            roster_ids = [
                child.id
                for child, _cls in _roster_children(session, workspace, age_band, reference_date)
            ]
            q = (
                sa.select(DocumentRecord)
                .outerjoin(Child, DocumentRecord.child_id == Child.id)
                .where(
                    DocumentRecord.workspace_id == workspace,
                    DocumentRecord.doc_type == "child_record",
                )
            )
            if roster_ids:
                q = q.where(DocumentRecord.child_id.in_(roster_ids))
            q = q.order_by(Child.display_name, DocumentRecord.target_period)
            entries: list[dict] = []
            for doc in session.scalars(q):
                version = session.scalar(
                    sa.select(DocumentVersion).where(DocumentVersion.id == doc.current_version_id)
                )
                if version is None:
                    continue
                # 名簿なしの降格時のみ entry の年齢帯でフィルタ（名簿ありは在籍で確定済み＝全期を通す）。
                if not roster_ids and (version.entry.get("age_band") or "0-2") != age_band:
                    continue
                entries.append(version.entry)
            return entries
    except SQLAlchemyError:
        return []


def list_class_monthly_entries(
    age_band: str, before_month: str | None = None, *, workspace_id: str | uuid.UUID | None = None
) -> list[dict]:
    """クラス（年齢帯）の作成済みクラス月案の最新版 entry を月順に返す＝クラス月案の「それまで」seed。

    **全期（年度跨ぎ含む）**を対象に、`before_month`（"YYYY-MM"）より前の月だけ返す（＝作成対象の月
    そのものは含めない。ゼロ埋め YYYY-MM は辞書順＝時系列）。クラス月案は主対象児なし・年齢帯は
    entry 内のため Python 側でフィルタ。降格・障害・該当なしは空。
    """
    eng = _engine()
    if eng is None:
        return []
    try:
        workspace = _workspace_uuid(workspace_id)
        with Session(eng) as session:
            q = (
                sa.select(DocumentRecord)
                .where(
                    DocumentRecord.workspace_id == workspace,
                    DocumentRecord.doc_type == "class_monthly",
                )
                .order_by(DocumentRecord.target_month)
            )
            if before_month is not None and before_month.strip():
                # 保存側 target_month はゼロ詰め正規化済み。比較境界も同じ正準形に揃える
                # （"2026-7" のような非ゼロ詰めが辞書順比較を壊すのを防ぐ）。解釈不能はそのまま使う。
                try:
                    boundary_month = normalize_month(before_month)
                except ValueError:
                    boundary_month = before_month.strip()
                q = q.where(DocumentRecord.target_month < boundary_month)
            entries: list[dict] = []
            for doc in session.scalars(q):
                version = session.scalar(
                    sa.select(DocumentVersion).where(DocumentVersion.id == doc.current_version_id)
                )
                if version is None:
                    continue
                if (version.entry.get("age_band") or "0-2") != age_band:
                    continue
                entries.append(version.entry)
            return entries
    except SQLAlchemyError:
        return []


def _entry_has_uncovered_note(entry: dict, by_child: dict[str, date]) -> bool:
    """日誌 entry が「経過記録に未反映の個別記録」を1件でも含むか（児童別境界）。

    その児の反映済み最終日（`by_child`）より後の日誌 note か、記録が1件も無い児（境界なし）の note が
    あれば未反映とみなす。日付が読めない entry は安全側で残す（情報を落とさない）。
    """
    try:
        d = date.fromisoformat(str(entry.get("date") or ""))
    except (ValueError, TypeError):
        return True
    for note in entry.get("individual_notes") or []:
        if not isinstance(note, dict):
            continue
        cov = by_child.get(str(note.get("child_id") or ""))
        if cov is None or d > cov:
            return True
    return False


def class_monthly_seed_inputs(
    age_band: str, month: str, *, workspace_id: str | uuid.UUID | None = None
) -> dict:
    """クラス月案の seed 入力（3系統＋在籍児名簿）をアーカイブから決定的に合成する（依存モデル 2026-07）。

    ① class_record_entries＝クラス児童の作成済み保育経過記録すべて（全期・年度跨ぎ含む）
    ② past_class_plans＝当該クラスの作成済みクラス月案すべて（対象月より前・全期）
    ③ class_diary_entries＝**経過記録にまだ反映されていない当該クラスの日誌**（対象月の前月末まで）。
    ④ class_roster＝クラスの在籍児名簿（`class_roster`＝0–2 個人目標の対象の与件・名簿未整備は空）。
       未反映判定は**児童別**（`covered_until_by_child`）＝各児の反映済み最終日より後の note を1件でも
       含む日誌を残す。クラス一律の max 境界だと記録が進んだ児に引きずられて、記録が遅れている児
       （途中入園児等）の日誌が丸ごと落ちるため（安全側＝情報を落とさない）。探索範囲は当該**年度**内に
       限る（`fiscal_year_start`＝同じ年齢帯でも前年度は別コホート）。実際の note 単位の絞り込み（反映済み
       note を除く集積）は下流の `aggregate.aggregate_by_child(covered_by_child=…)` が担う（決定実体は1つ）。
    scripts（run_class_monthly）と web（/api/records/class-monthly-seed）が共用する合成。month が不正なら
    ValueError（呼び出し側がサンプル降格/400 にする）。未接続は全部空（呼び出し側がサンプル降格）。
    """
    month = normalize_month(
        month
    )  # ゼロ詰め正準化（不正 month は ValueError＝呼び出し側が降格/400）
    _, prev_month_end = month_date_range(prev_month_of(month))
    diary_from = fiscal_year_start(month)  # 同一コホート（当該年度）に限る探索下限
    records = list_class_child_record_entries(age_band, as_of=diary_from, workspace_id=workspace_id)
    by_child = covered_until_by_child(records)
    diaries = [
        e
        for e in list_diary_entries(diary_from, prev_month_end, workspace_id=workspace_id)
        if (e.get("age_band") or "0-2") == age_band and _entry_has_uncovered_note(e, by_child)
    ]
    return {
        "class_diary_entries": diaries,
        "class_record_entries": records,
        "past_class_plans": list_class_monthly_entries(
            age_band, before_month=month, workspace_id=workspace_id
        ),
        # 在籍児名簿（クラス・園児マスタ）＝0–2 個人目標の対象の与件（依存モデルの3系統に加える第4の与件。
        # 名簿未整備・未接続は空＝fetch_reference が「名簿なし」を正直に author へ伝える）。
        "class_roster": class_roster(age_band, month, workspace_id=workspace_id),
    }


def _child_view(c: Child, cls: Class | None = None) -> dict:
    """児童マスタ行→UI/描画用の dict（本名の合成＝氏名欄用の official_name＋所属クラスを含む）。

    `cls` を渡すと所属クラス名を添える（名簿UIのグループ表示用）。年齢帯はクラスの属性でなく、書類の
    対象年度と生年月日から導出する。渡さないと class_name は空（get_child/upsert_child の名前解決用途）。
    """
    return {
        "id": str(c.id),
        "display_name": c.display_name,
        "family_name": c.family_name or "",
        "given_name": c.given_name or "",
        "gender": c.gender or "",
        "official_name": official_full_name(c.family_name, c.given_name),  # 氏名欄用（姓＋名）
        "birthdate": c.birthdate.isoformat() if c.birthdate else None,
        "class_id": str(c.class_id) if c.class_id else None,
        "class_name": cls.name if cls else "",
    }


def list_children(*, workspace_id: str | uuid.UUID | None = None) -> list[dict]:
    """児童マスタ（active のみ・表示名順）。UI の子ども選択肢（降格は空＝従来チップへ）。

    各児に所属クラス名を添える＝名簿UIの「未所属／各クラス」グループ化に使う（クラス表を1回引いて
    map で解決＝N+1 を避ける）。
    """
    eng = _engine()
    if eng is None:
        return []
    try:
        workspace = _workspace_uuid(workspace_id)
        with Session(eng) as session:
            classes = {
                c.id: c
                for c in session.scalars(sa.select(Class).where(Class.workspace_id == workspace))
            }
            children = session.scalars(
                sa.select(Child)
                .where(Child.workspace_id == workspace, Child.active.is_(True))
                .order_by(Child.display_name)
            )
            return [_child_view(c, classes.get(c.class_id)) for c in children]
    except SQLAlchemyError:
        return []


# ──────────────────────────── クラス（組）マスタ：CRUD＋roster（名簿管理・日誌 roster の素） ────────────────────────────


def _class_view(c: Class, children: Iterable[Child] = ()) -> dict:
    """クラス行→UI 用の dict（年齢帯は在籍児と年度から導出して添える）。"""
    members = list(children)
    reference_date = fiscal_year_start_for_year(c.fiscal_year)
    age_bands = [
        band
        for band in AGE_BANDS
        if any(age_band_for_birthdate(child.birthdate, reference_date) == band for child in members)
    ]
    view = {
        "id": str(c.id),
        "name": c.name,
        "age_bands": age_bands,
        "fiscal_year": c.fiscal_year or "",
        "active": c.active,
        "child_count": len(members),
    }
    return view


def list_classes(
    fiscal_year: str | None = None,
    active_only: bool = True,
    *,
    workspace_id: str | uuid.UUID | None = None,
) -> list[dict]:
    """クラス一覧（年度降順→組名）。在籍児数と導出年齢帯を添える。降格・障害は空。"""
    eng = _engine()
    if eng is None:
        return []
    try:
        workspace = _workspace_uuid(workspace_id)
        with Session(eng) as session:
            q = sa.select(Class).where(Class.workspace_id == workspace)
            if active_only:
                q = q.where(Class.active.is_(True))
            if fiscal_year:
                q = q.where(Class.fiscal_year == fiscal_year.strip())
            q = q.order_by(Class.fiscal_year.desc(), Class.name)
            classes = list(session.scalars(q))
            by_class: dict[uuid.UUID, list[Child]] = {}
            for child in session.scalars(
                sa.select(Child).where(
                    Child.workspace_id == workspace,
                    Child.active.is_(True),
                    Child.class_id.is_not(None),
                )
            ):
                if child.class_id is not None:
                    by_class.setdefault(child.class_id, []).append(child)
            return [_class_view(c, by_class.get(c.id, [])) for c in classes]
    except SQLAlchemyError:
        return []


def list_children_in_class(
    class_id: str, *, workspace_id: str | uuid.UUID | None = None
) -> list[dict]:
    """指定クラスの在籍児（active・表示名順）＝日誌フォームの roster／名簿UIのクラス内一覧の素。

    不正 id・未接続・障害・該当なしは空（読取は落とさない）。年齢帯決定のためクラス情報も child_view に添える。
    """
    eng = _engine()
    if eng is None:
        return []
    try:
        target = uuid.UUID(class_id)
    except (ValueError, AttributeError):
        return []
    try:
        workspace = _workspace_uuid(workspace_id)
        with Session(eng) as session:
            cls = session.scalar(
                sa.select(Class).where(Class.id == target, Class.workspace_id == workspace)
            )
            if cls is None:
                return []
            children = session.scalars(
                sa.select(Child)
                .where(
                    Child.workspace_id == workspace,
                    Child.class_id == target,
                    Child.active.is_(True),
                )
                .order_by(Child.display_name)
            )
            return [_child_view(c, cls) for c in children]
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


def list_feedback(
    document_id: str | None = None,
    limit: int = 100,
    *,
    workspace_id: str | uuid.UUID | None = None,
) -> list[dict]:
    """書類フィードバック（👍👎＋ひとこと）の一覧（新しい順）。

    document_id を与えるとその書類の分だけ返す（確定画面／「書類を見る」タブで既存フィードバックを
    表示する用）。version_seq も添える（どの版への評価か）。降格・障害・不正 id は空（読取は落とさない
    ＝list_audit_events と同じ）。
    """
    eng = _engine()
    if eng is None:
        return []
    try:
        workspace = _workspace_uuid(workspace_id)
        with Session(eng) as session:
            q = (
                sa.select(Feedback)
                .where(Feedback.workspace_id == workspace)
                .order_by(Feedback.created_at.desc())
                .limit(limit)
            )
            if document_id:
                q = q.where(Feedback.document_id == uuid.UUID(document_id))
            rows = list(session.scalars(q))
            # 版 id → seq を1回で解決（N+1 を避ける）。版が引けないものは seq 0。
            version_ids = {f.version_id for f in rows if f.version_id is not None}
            seq_by_version: dict[uuid.UUID, int] = {}
            if version_ids:
                seq_by_version = dict(
                    session.execute(
                        sa.select(DocumentVersion.id, DocumentVersion.seq).where(
                            DocumentVersion.id.in_(version_ids)
                        )
                    ).all()
                )
            return [
                {
                    "id": str(f.id),
                    "document_id": str(f.document_id),
                    "verdict": f.verdict,
                    "comment": f.comment,
                    "actor": f.actor,
                    "version_seq": seq_by_version.get(f.version_id, 0),
                    "at": f.created_at.isoformat(),
                }
                for f in rows
            ]
    except (ValueError, SQLAlchemyError):
        return []
