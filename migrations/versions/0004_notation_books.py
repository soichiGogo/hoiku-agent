"""表記ルール辞書（notation_books）＝ひらがな表記DXの決定的ストア（Cloud SQL 統合）。

book 丸ごと JSON（PG は JSONB）1行が SSOT・version は楽観ロック用（policy_books と同形）。
モデルの SSOT は src/hoiku_agent/harness/notation_store.py（本ファイルはその適用手順）。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

_JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "notation_books",
        sa.Column("id", sa.String(20), primary_key=True),
        sa.Column("book", _JSON, nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("notation_books")
