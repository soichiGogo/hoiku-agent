"""書類の要件・レビュー項目・生成結果のスキーマ。

`プロダクト方針.md` §1 の input/process/output に対応：
- DocumentSpec   … input「書類の要件情報」（どの情報を参照すべきか・書式）
- ReviewCriteria … input「レビュー項目」（前年データ準拠・先輩の指摘など、ユーザーが育てる）
- ReviewFinding  … レビューAIの指摘1件
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class DocumentType(str, Enum):
    """対象書類。国が課す必須文書を土台に、ヒアリングで対象を絞っていく（プロダクト方針 §5/§6）。"""

    年間計画 = "年間計画"
    月案 = "月案"
    週案 = "週案"
    日案 = "日案"
    連絡帳 = "連絡帳"
    お便り = "お便り"
    保育日誌 = "保育日誌"
    シフト = "シフト"


class DocumentSpec(BaseModel):
    """書類ごとの要件。ユーザーが調整可能（プロダクト方針 §1 input）。"""

    doc_type: DocumentType
    # 章立て・必須項目（＝ワークフロー層が"型"として保証する対象）
    required_sections: list[str] = Field(default_factory=list)
    # この書類作成時に参照すべき情報源（過去資料・指針・園のスケジュール 等）
    reference_sources: list[str] = Field(default_factory=list)
    # 出力フォーマットの指定（雛形があればそのパス等）
    template_ref: str | None = None


class ReviewCriteria(BaseModel):
    """レビュー観点。先輩の添削ポイント等をユーザーが追加・蓄積していく（プロダクト方針 §1/§4）。"""

    item: str
    rationale: str | None = None  # なぜこの観点か（指針整合・園ルール 等）


class ReviewFinding(BaseModel):
    """レビューAIの指摘1件。修正差分は eval（層B）へ還元する（プロダクト方針 §4）。"""

    criterion: str
    severity: str = "info"  # info / warn / must_fix
    message: str
    suggestion: str | None = None
