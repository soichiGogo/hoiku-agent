"""ユーザーごとの個人ワークスペースでアーカイブを隔離する。

既存データは推測で既存 Google ユーザーへ配らず、専用の「既存データ」領域へ退避する。email の一致だけで
所有者を判定すると、異なる Google account に個人情報を誤開示するおそれがあるためである。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None

LEGACY_WORKSPACE_ID = "00000000-0000-0000-0000-000000000011"


def upgrade() -> None:
    op.alter_column("policy_books", "id", existing_type=sa.String(20), type_=sa.String(64))
    op.alter_column("notation_books", "id", existing_type=sa.String(20), type_=sa.String(64))
    op.create_table(
        "workspaces",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False, server_default=""),
        sa.Column("is_legacy", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.execute(
        sa.text(
            "INSERT INTO workspaces (id, name, is_legacy, created_at, updated_at) "
            "VALUES (CAST(:id AS uuid), '既存データ', true, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        ).bindparams(id=LEGACY_WORKSPACE_ID)
    )
    for table in ("children", "classes", "documents", "feedback"):
        op.add_column(table, sa.Column("workspace_id", sa.Uuid(), nullable=True))
        op.execute(
            sa.text(f"UPDATE {table} SET workspace_id = CAST(:id AS uuid)").bindparams(
                id=LEGACY_WORKSPACE_ID
            )
        )
        op.alter_column(table, "workspace_id", nullable=False)
        op.create_foreign_key(
            f"fk_{table}_workspace", table, "workspaces", ["workspace_id"], ["id"]
        )
        op.create_index(f"ix_{table}_workspace_id", table, ["workspace_id"])

    op.add_column("users", sa.Column("workspace_id", sa.Uuid(), nullable=True))
    op.create_foreign_key("fk_users_workspace", "users", "workspaces", ["workspace_id"], ["id"])
    op.create_index("ix_users_workspace_id", "users", ["workspace_id"])

    op.drop_constraint("children_display_name_key", "children", type_="unique")
    op.create_unique_constraint(
        "uq_children_workspace_display_name", "children", ["workspace_id", "display_name"]
    )
    op.drop_constraint("uq_classes_name_fiscal_year", "classes", type_="unique")
    op.create_unique_constraint(
        "uq_classes_workspace_name_year", "classes", ["workspace_id", "name", "fiscal_year"]
    )
    op.drop_constraint("documents_dedupe_key_key", "documents", type_="unique")
    op.create_unique_constraint(
        "uq_documents_workspace_dedupe", "documents", ["workspace_id", "dedupe_key"]
    )
    op.create_table(
        "deletion_requests",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id"), nullable=False, index=True
        ),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("email", sa.String(200), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("requested_at", sa.DateTime(), nullable=False, index=True),
        sa.Column("due_at", sa.DateTime(), nullable=False, index=True),
        sa.Column("processed_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("deletion_requests")
    op.drop_constraint("uq_documents_workspace_dedupe", "documents", type_="unique")
    op.create_unique_constraint("documents_dedupe_key_key", "documents", ["dedupe_key"])
    op.drop_constraint("uq_classes_workspace_name_year", "classes", type_="unique")
    op.create_unique_constraint("uq_classes_name_fiscal_year", "classes", ["name", "fiscal_year"])
    op.drop_constraint("uq_children_workspace_display_name", "children", type_="unique")
    op.create_unique_constraint("children_display_name_key", "children", ["display_name"])
    op.drop_constraint("fk_users_workspace", "users", type_="foreignkey")
    op.drop_index("ix_users_workspace_id", table_name="users")
    op.drop_column("users", "workspace_id")
    for table in ("feedback", "documents", "classes", "children"):
        op.drop_constraint(f"fk_{table}_workspace", table, type_="foreignkey")
        op.drop_index(f"ix_{table}_workspace_id", table_name=table)
        op.drop_column(table, "workspace_id")
    op.drop_table("workspaces")
    op.alter_column("notation_books", "id", existing_type=sa.String(64), type_=sa.String(20))
    op.alter_column("policy_books", "id", existing_type=sa.String(64), type_=sa.String(20))
