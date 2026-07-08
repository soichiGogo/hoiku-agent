"""書類フィードバック（👍👎＋ひとこと）テーブルを追加する（確定/承認画面からの軽量フィードバック導線）。

背景（設計判断・§4/§8「回す」）：これまで「回す（改善サイクル）」の一次入力＝保育士の修正メモ・👍👎 は
`/api/improve` に transient で渡すだけで、どこにも永続化されず特定の書類にも紐付いていなかった。書類作成を
通して改善が自然に進むよう、確定/承認画面から送る 👍👎＋ひとことを **文書＋その版**に紐付けて残す。

- feedback：document_id（対象書類）＋ version_id（送信時点の現行版＝どの本文への評価か）＋ verdict（up/down）
  ＋ comment（ひとこと・任意）＋ actor（担当者）。audit_events（誰が finalize/edit/approve/import したかの証跡）
  とは意味論が別なので独立テーブルにする（同じ関心事を別の場所で二重に表現しない）。

モデルの SSOT は src/hoiku_agent/harness/record_store.py（本ファイルはその適用手順）。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "feedback",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "document_id", sa.Uuid(), sa.ForeignKey("documents.id"), nullable=False, index=True
        ),
        sa.Column("version_id", sa.Uuid(), sa.ForeignKey("document_versions.id"), nullable=True),
        sa.Column("verdict", sa.String(4), nullable=False),
        sa.Column("comment", sa.Text(), nullable=False),
        sa.Column("actor", sa.String(100), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, index=True),
    )


def downgrade() -> None:
    op.drop_table("feedback")
