"""様式テンプレート＝書類レイアウトの宣言的スキーマ（pydantic）。

設計コンテキスト §5/§18。書類の**本文レイアウト（章立て＝セクションの順序・見出しラベル・種別・
任意欄の出し分け）をコードでなくデータ（`knowledge/様式テンプレート.json`）で持つ**ための型。
`harness/draft.py` のテキスト整形（と後続で帳票PDF・編集フォーム）がこのテンプレを歩いて描くことで、
レイアウトの二重管理を解消し、特定園の様式差（§18）をコード改修でなくテンプレ編集で吸収できる。

責務の線（§5）：**テンプレはレイアウトのデータのみ**。必須欄・年齢分岐の検査は `schema_check.py`、
フィールドの SSOT は `schemas/document.py`（不変）。テンプレに validation を持たせない。
ヘッダの合成・個別記録ブロック等の**構造的な描画はコード**に残し、テンプレは本文セクションの
順序/ラベル/種別/出し分けを持つ（＝式言語を作らず、閉じた語彙に留める）。

- SectionKind … セクションの描画種別（コード側レンダラを1つ選ぶ・閉じた列挙）。
- ShowRule … 任意欄の出し分け（常時／非空のときだけ）。
- Section … 本文1セクション（読む entry フィールド key・見出し label・種別・空欄プレースホルダ）。
- DocTemplate … 1書類種別（doc_type）の本文セクション列。
- TemplateBook … 全書類のテンプレ集合（`様式テンプレート.json` の正・version は楽観ロック用）。

スキーマは本パッケージに集約し二重定義しない（規約: schemas/ 集約）。notation/policy と同じく book
丸ごと JSON 1行を SSOT とし DB へ行射影しない（置き場は harness/template_store が解決）。
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class SectionKind(str, Enum):
    """本文セクションの描画種別。テンプレは種別名で**コード側の描画関数を1つ選ぶ**（式言語は作らない）。

    - text_block … 見出し行＋インデントした本文（`【label】\\n  {値 or blank}`）。
    - text_inline … 見出しと本文を同じ行に（`【label】 {値 or blank}`）。
    - attendance … 出欠のサマリ（`【label】 {出席N名 / 欠席:…}`）。日誌のみ。
    - individual_notes … 個別の記録（児ごとの姿＋タグ＋生活記録＋個人のねらい）。日誌のみの特殊ブロック。
    - tagged_list … 枠組みタグ付きの叙述リスト（`【label】\\n  - {item}\\n    └ 対応する姿/領域: {tags}`）。
      月案の教育／児童票・要録の発達の経過で共用（読む item フィールドは item_field で切替）。
    - evaluation2 … 日誌の評価・反省（2視点の (a)/(b) 行）。日誌のみの特殊ブロック。
    """

    text_block = "text_block"
    text_inline = "text_inline"
    attendance = "attendance"
    individual_notes = "individual_notes"
    tagged_list = "tagged_list"
    evaluation2 = "evaluation2"


class ShowRule(str, Enum):
    """セクションの出し分け（決定的・閉じた語彙）。"""

    always = "always"  # 常に出す（空でも blank プレースホルダで出す）
    nonblank = "nonblank"  # 対象フィールドが空なら丸ごと出さない（任意セクション）


class Section(BaseModel):
    """本文1セクションのレイアウト定義（レイアウトのデータのみ・描画ロジックは持たない）。"""

    key: str = Field(
        description="読む entry フィールド名（text_*=文字列欄／tagged_list=リスト欄／"
        "individual_notes・attendance・evaluation2 は種別が既定の欄を読む）"
    )
    label: str = Field(
        description="見出しラベル（【】内。園差で改名しうる＝テンプレ編集で吸収する部分）"
    )
    kind: SectionKind
    blank: str = Field(
        default="",
        description="対象フィールドが空のときに出すプレースホルダ（例: （未記入）/特記なし/なし）",
    )
    show: ShowRule = ShowRule.always
    item_field: str | None = Field(
        default=None,
        description="tagged_list が各要素から読む叙述フィールド名（月案=aim／児童票・要録=description）",
    )


class DocTemplate(BaseModel):
    """1書類種別（doc_type）の本文セクション列。ヘッダはコードが合成する（テンプレは本文を持つ）。"""

    doc_type: str = Field(description="diary / monthly / child_record / nursery_record")
    sections: list[Section] = Field(default_factory=list)


class TemplateBook(BaseModel):
    """全書類の様式テンプレ集合。`knowledge/様式テンプレート.json` の正（SSOT）。

    notation/policy と同じく book 丸ごと JSON 1行を SSOT とし行射影しない。version は楽観ロック用。
    """

    version: int = 1  # 将来のスキーマ移行用
    templates: list[DocTemplate] = Field(default_factory=list)
