"""児童マスタに本名（姓/名）と性別を追加する（呼び名＋敬称の分離・氏名欄の本名化）。

背景（設計判断）：これまで child_id＝表示名（"はるとくん"）が「日誌本文の主語」と「保育要録/児童票の
氏名欄」を一本で兼ねていた。名前と敬称を潰しているため、① 新規児の入力ゆれで重複児が生まれ、
② 氏名欄に敬称込みの呼び名が出てしまう（就学先引継ぎの公式様式としては本名＝姓名が正しい）。

そこで children に本名（family_name/given_name）と gender を持たせて要素を分ける:
- display_name（呼び名＋敬称）は **child_id の同定キーとして不変**（書類 JSON/LLM/eval は無改修）。
- gender→敬称（男→くん/女→ちゃん）で表示名を合成、氏名欄は family_name＋given_name（本名）で描く。
- 既存行は display_name の末尾敬称から given_name/gender を back-fill（姓は不明＝空のまま）。

モデルの SSOT は src/hoiku_agent/harness/record_store.py（本ファイルはその適用手順）。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("children", sa.Column("family_name", sa.String(50), nullable=True))
    op.add_column("children", sa.Column("given_name", sa.String(50), nullable=True))
    op.add_column("children", sa.Column("gender", sa.String(10), nullable=True))

    # 既存行の back-fill：呼び名＋敬称（display_name）から名と性別を復元（PostgreSQL。姓は不明＝空）。
    # くん（2文字）→male / ちゃん（3文字）→female。さん・その他は判定不能として据え置く。
    op.execute(
        """
        UPDATE children
        SET gender = 'male',
            given_name = left(display_name, char_length(display_name) - 2)
        WHERE display_name LIKE '%くん'
          AND (given_name IS NULL OR given_name = '')
        """
    )
    op.execute(
        """
        UPDATE children
        SET gender = 'female',
            given_name = left(display_name, char_length(display_name) - 3)
        WHERE display_name LIKE '%ちゃん'
          AND (given_name IS NULL OR given_name = '')
        """
    )


def downgrade() -> None:
    op.drop_column("children", "gender")
    op.drop_column("children", "given_name")
    op.drop_column("children", "family_name")
