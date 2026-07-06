"""クラス（組）マスタと児童の所属（children.class_id）を追加する（園の名簿管理・日誌 roster の素）。

背景（設計判断）：これまでクラスは一次エンティティとして存在せず、書類 JSON 内の `class_name`
（自由記述）と `age_band` でしか表現されていなかった。日誌の手入力フォーム（在籍児の一括 roster）・
年齢帯の自動決定・園児登録の受け皿として、クラスを一次化する。

- classes：同一性は (name, fiscal_year)＝進級で組名が再利用されても年度で分かれる。
- children.class_id：現在の所属1本（v0）。年度またぎの履歴は書類 JSON が作成時の age_band/組名を
  既に保持するため持たない（§18 と同じ現場依存＝残課題）。未所属は NULL。

モデルの SSOT は src/hoiku_agent/harness/record_store.py（本ファイルはその適用手順）。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "classes",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(50), nullable=False),
        sa.Column("age_band", sa.String(10), nullable=False),
        sa.Column("fiscal_year", sa.String(10), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("name", "fiscal_year", name="uq_classes_name_fiscal_year"),
    )
    # children に class_id（FK）＋索引を足す。ALTER で FK を足すのは sqlite が非対応なので batch モード
    # で行う（Postgres は通常の ALTER・sqlite は copy-and-move で再構築＝どちらでも通る）。実 DB は
    # Cloud SQL PostgreSQL だが、ローカル sqlite での `alembic upgrade head` も壊さない（0006 と同じ配慮）。
    with op.batch_alter_table("children") as batch_op:
        batch_op.add_column(sa.Column("class_id", sa.Uuid(), nullable=True))
        batch_op.create_foreign_key("fk_children_class_id", "classes", ["class_id"], ["id"])
        batch_op.create_index("ix_children_class_id", ["class_id"])


def downgrade() -> None:
    with op.batch_alter_table("children") as batch_op:
        batch_op.drop_index("ix_children_class_id")
        batch_op.drop_constraint("fk_children_class_id", type_="foreignkey")
        batch_op.drop_column("class_id")
    op.drop_table("classes")
