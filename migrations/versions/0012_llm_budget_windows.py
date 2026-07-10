"""LLM 利用枠の予約窓を追加する。"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "llm_budget_windows",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("scope", sa.String(20), nullable=False, index=True),
        sa.Column("subject", sa.String(255), nullable=False, index=True),
        sa.Column("window_start", sa.DateTime(), nullable=False, index=True),
        sa.Column("reserved_micro_yen", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("scope", "subject", "window_start"),
    )


def downgrade() -> None:
    op.drop_table("llm_budget_windows")
