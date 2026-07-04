"""書類アーカイブの初期スキーマ（children / documents / document_versions / audit_events）。

Phase 1（本番運用ブラッシュアップ 2026-07）。モデルの SSOT は
src/hoiku_agent/harness/record_store.py（本ファイルはその適用手順）。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

_JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "children",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("display_name", sa.String(100), nullable=False, unique=True),
        sa.Column("official_name", sa.String(100), nullable=True),
        sa.Column("birthdate", sa.Date(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "documents",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("doc_type", sa.String(20), nullable=False, index=True),
        sa.Column("dedupe_key", sa.String(200), nullable=False, unique=True),
        sa.Column("child_id", sa.Uuid(), sa.ForeignKey("children.id"), nullable=True, index=True),
        sa.Column("target_date", sa.Date(), nullable=True, index=True),
        sa.Column("target_month", sa.String(7), nullable=True),
        sa.Column("target_period", sa.String(50), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("current_version_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "document_versions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "document_id", sa.Uuid(), sa.ForeignKey("documents.id"), nullable=False, index=True
        ),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("entry", _JSON, nullable=False),
        sa.Column("rendered_text", sa.Text(), nullable=False),
        sa.Column("author_kind", sa.String(20), nullable=False),
        sa.Column("created_by", sa.String(100), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("document_id", "seq"),
    )
    op.create_table(
        "audit_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "document_id", sa.Uuid(), sa.ForeignKey("documents.id"), nullable=True, index=True
        ),
        sa.Column("actor", sa.String(100), nullable=False),
        sa.Column("action", sa.String(30), nullable=False),
        sa.Column("detail", _JSON, nullable=False),
        sa.Column("at", sa.DateTime(), nullable=False, index=True),
    )


def downgrade() -> None:
    op.drop_table("audit_events")
    op.drop_table("document_versions")
    op.drop_table("documents")
    op.drop_table("children")
