"""documents に登場する子ども（mentioned_children）の索引を追加する（書類を見るタブの対象児フィルタ）。

背景（設計判断）：保育日誌・クラス月案は1書類にクラス全体（複数児）の記録が同居し、既存の
documents.child_id（単一FK・主対象児専用の書類だけが持つ）では引けない。既存の
harness.record_store._mentioned_children()（保存時に児童マスタの auto-create にしか使っていなかった）
の出力を「検索キーの列昇格」として documents.mentioned_children（JSON配列＝表示名のリスト）へ永続化する。
本文JSONがSSOT・検索キーだけ列昇格という record_store.py の既存方針にそのまま乗る（射影テーブルは作らない）。

既存行は現行版の entry から同じ抽出規則の凍結コピーで back-fill する（アプリ側 record_store.py が将来
変わっても過去の migration は独立して再現できるよう、規則をここに複製する＝0006 と同じ配慮）。

モデルの SSOT は src/hoiku_agent/harness/record_store.py（本ファイルはその適用手順）。
"""

from __future__ import annotations

import json

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None

_JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def _mentioned_children(doc_type: str, entry: dict) -> list[str]:
    """harness.record_store._mentioned_children の抽出規則の凍結コピー（migration 0014 時点）。"""
    names: list[str] = []
    if doc_type in ("monthly", "child_record", "nursery_record"):
        main = str(entry.get("child_id") or "").strip()
        if main:
            names.append(main)
    elif doc_type == "diary":
        for note in entry.get("individual_notes") or []:
            name = str((note or {}).get("child_id") or "").strip()
            if name and name not in names:
                names.append(name)
        for att in entry.get("attendance") or []:
            name = str((att or {}).get("child_id") or "").strip()
            if name and name not in names:
                names.append(name)
    elif doc_type == "class_monthly":
        for goal in entry.get("individual_goals") or []:
            name = str((goal or {}).get("child_id") or "").strip()
            if name and name not in names:
                names.append(name)
    return names


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column("mentioned_children", _JSON, nullable=False, server_default="[]"),
    )
    conn = op.get_bind()
    meta = sa.MetaData()
    documents = sa.Table("documents", meta, autoload_with=conn)
    versions = sa.Table("document_versions", meta, autoload_with=conn)
    rows = conn.execute(
        sa.select(documents.c.id, documents.c.doc_type, documents.c.current_version_id)
    ).fetchall()
    for doc_id, doc_type, current_version_id in rows:
        if current_version_id is None:
            continue
        version = conn.execute(
            sa.select(versions.c.entry).where(versions.c.id == current_version_id)
        ).first()
        if version is None:
            continue
        # entry の型は方言のJSON実装/reflectionの揺れで dict のことも JSON 文字列のこともある
        # （PostgreSQL の JSONB は dict で返る想定・sqlite reflection は素の文字列で返ることがある）。
        # どちらでも decode できるようにし、壊れた行はスキップする（backfill を fail-loud にしない）。
        raw_entry = version.entry
        if isinstance(raw_entry, str):
            try:
                raw_entry = json.loads(raw_entry)
            except ValueError:
                continue
        names = _mentioned_children(doc_type, raw_entry or {})
        if names:
            conn.execute(
                documents.update().where(documents.c.id == doc_id).values(mentioned_children=names)
            )


def downgrade() -> None:
    op.drop_column("documents", "mentioned_children")
