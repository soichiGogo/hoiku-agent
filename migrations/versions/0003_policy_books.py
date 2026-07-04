"""育つ指針＝カードブック（policy_books）＝GCS から Cloud SQL への統合（Phase 2）。

book 丸ごと JSON（PG は JSONB）1行が SSOT・version は楽観ロック用（GCS generation の置き換え）。
モデルの SSOT は src/hoiku_agent/harness/policy_store.py（本ファイルはその適用手順）。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

_JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "policy_books",
        sa.Column("id", sa.String(20), primary_key=True),
        sa.Column("book", _JSON, nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("policy_books")
