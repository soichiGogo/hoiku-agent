"""クラスの固定年齢帯を廃止する。

クラス編成は同年齢だけに限らず、異年齢編成もある。classes.age_band は入力時の推測値であり、在籍児の
構成と矛盾し得るため廃止する。年齢帯は children.birthdate と対象年度の4月1日から record_store が
導出し、書類そのものの age_band は従来どおり本文 JSON に保持する。

モデルの SSOT は src/hoiku_agent/harness/record_store.py（本ファイルはその適用手順）。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # SQLite のテスト環境と PostgreSQL の双方で動かすため batch モードを使う。
    with op.batch_alter_table("classes") as batch_op:
        batch_op.drop_column("age_band")


def downgrade() -> None:
    # 旧スキーマへ戻す場合の埋め値。年齢帯の真値は在籍児から再導出するため、旧列へは保存しない。
    with op.batch_alter_table("classes") as batch_op:
        batch_op.add_column(
            sa.Column("age_band", sa.String(10), nullable=False, server_default="0-2")
        )
