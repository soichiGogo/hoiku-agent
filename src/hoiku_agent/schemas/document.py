"""書類の要件・レビュー項目・生成物のスキーマ（pydantic）。

設計コンテキスト §10「データモデル／フィールド依存（第1号スキーマ）」に対応。第1号＝
月案＋保育日誌・0–2歳児クラス（個別）。欄名対応は推論を含むため Field description に明記する
（制度用語と断定しない＝§10 / Certainty）。実様式1枚をヒアリングで入手するまでの暫定型だが
この型で着手してよい（§10・§18）。

- DocumentType / DocumentSpec … input「書類の要件」（どの欄・どの順・参照元・年齢分岐）。
- ReviewCriteria / ReviewFinding … レビューAIの観点と指摘（§7）。修正差分は eval（層B）へ還元。
- DiaryEntry ほか … 日誌v0 の出力型（write_draft の出力 / validate_fields の入力契約）。

スキーマは本パッケージに集約し、同じ関心事を別所で二重定義しない（規約: schemas/ 集約）。
"""

from __future__ import annotations

from datetime import date
from enum import Enum

from pydantic import BaseModel, Field

from .domain import FiveDomains, TenNoSugata, ThreeViewpoint
from .enums import AgeBand


class DocumentType(str, Enum):
    """対象書類。国が課す必須文書を土台に対象を絞る（§2/§3）。第1号は 月案・保育日誌。"""

    年間計画 = "年間計画"
    月案 = "月案"
    週案 = "週案"
    日案 = "日案"
    連絡帳 = "連絡帳"
    お便り = "お便り"
    保育日誌 = "保育日誌"
    シフト = "シフト"


class DocumentSpec(BaseModel):
    """書類ごとの要件。ユーザーが調整可能（§10 input）。

    年齢分岐は必須（§10）：age_band により validate_fields がタグ要件を分岐させる
    （0–2＝ThreeViewpoint / 3–5＝FiveDomains）。
    """

    doc_type: DocumentType
    age_band: AgeBand
    # 章立て・必須項目（＝harness が "型" として充足保証する対象）
    required_sections: list[str] = Field(default_factory=list)
    # 作成時に参照すべき情報源（過去資料・指針・園のスケジュール 等）
    reference_sources: list[str] = Field(default_factory=list)
    # 出力フォーマットの指定（雛形があればそのパス等）。越谷市様式末尾「など」＝園差で拡張可（§10）
    template_ref: str | None = None


class ReviewCriteria(BaseModel):
    """レビュー観点。先輩の添削ポイント等をユーザーが追加・蓄積（§7）。出所は育つ指針。"""

    item: str
    rationale: str | None = None  # なぜこの観点か（指針整合・園ルール 等）


class ReviewFinding(BaseModel):
    """レビューAIの指摘1件。修正差分は eval（層B）へ還元し「回した証拠」にする（§8/§12）。"""

    criterion: str
    severity: str = "info"  # info / warn / must_fix（must_fix は評価ゲートの違反0条件＝§12）
    message: str
    suggestion: str | None = None


# ──────────────────────────── 保育日誌 v0（0–2 個別） ────────────────────────────


class ChildAttendance(BaseModel):
    """出欠（と理由）。クラス日誌系統（§10）。"""

    child_id: str  # 架空児のみ。実名は書かない（§14）
    present: bool
    reason: str | None = None  # 欠席理由


class IndividualNote(BaseModel):
    """個別日誌（特記事項／個人記録）。0–2 個別の本体（§10・個別日誌系統）。"""

    child_id: str
    observed_state: str  # 当日の観察＝子どもの姿
    # タグ要件は年齢で分岐（0–2＝ThreeViewpoint / 3–5＝FiveDomains）。分岐の強制は validate_fields。
    tags: list[TenNoSugata | ThreeViewpoint | FiveDomains] = Field(default_factory=list)


class DiaryEvaluation(BaseModel):
    """評価・反省は必ず2視点を別フィールドで必須にする（§10）。両系統にまたがる。"""

    child_focus: str = Field(description="(a)子どもに焦点を当てた振り返り")
    self_review: str = Field(description="(b)自分のねらい・内容・環境構成・関わりの適否")


class DiaryEntry(BaseModel):
    """保育日誌（日次）。write_draft の出力型 / validate_fields の入力契約（§10）。

    欄名は越谷市様式等からの推論を含む（§10）。園差で拡張されうるため拡張可能に保つ。
    """

    date: date
    age_band: AgeBand
    weather: str
    attendance: list[ChildAttendance]  # クラス日誌
    health_notes: str | None = None  # クラス日誌
    practice_record: str = Field(  # クラス日誌（←日案←週案←月案ねらいにトップダウン一貫）
        description="保育の実践記録。日案←週案←月案のねらいにトップダウン一貫"
    )
    individual_notes: list[IndividualNote]  # 個別日誌（0–2 個別の本体）
    evaluation: DiaryEvaluation  # 両系統・2視点必須
    parent_contact: str | None = None  # クラス日誌
