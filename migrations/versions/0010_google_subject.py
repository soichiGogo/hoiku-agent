"""Google Sign-In の不変 subject を users に保持する。

email は変更・再利用され得るため、Google の検証済み identity の対応付けは OIDC の `sub` を正とする。
既存 IAP 利用者は次回の Google Sign-In 時に email 一致の行へ subject が補完される。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("google_subject", sa.String(255), nullable=True))
    op.create_unique_constraint("uq_users_google_subject", "users", ["google_subject"])


def downgrade() -> None:
    op.drop_constraint("uq_users_google_subject", "users", type_="unique")
    op.drop_column("users", "google_subject")
