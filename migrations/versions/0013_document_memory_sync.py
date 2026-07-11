"""承認版のMemory Bank同期状態を追加する。"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("memory_synced_version_id", sa.Uuid(), nullable=True))
    op.add_column("documents", sa.Column("memory_synced_at", sa.DateTime(), nullable=True))
    op.create_index(
        "ix_documents_memory_synced_version_id",
        "documents",
        ["memory_synced_version_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_documents_memory_synced_version_id", table_name="documents")
    op.drop_column("documents", "memory_synced_at")
    op.drop_column("documents", "memory_synced_version_id")
