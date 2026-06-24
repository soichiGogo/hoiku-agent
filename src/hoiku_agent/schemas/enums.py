"""年齢分岐・記録系統・確度メタの列挙型。

設計コンテキスト §10「データモデル／フィールド依存」に対応。
- AgeBand    … 月案/日誌共通の年齢分岐（0–2＝3つの視点 / 3–5＝5領域＋10の姿）。validate_fields の分岐キー。
- Lineage    … 日誌の各欄が「クラス日誌」か「個別日誌」かの系統タグ。
- Certainty  … 制度用語と断定しないための確度メタ（告示で裏取り済=確証 / 欄名対応=推論）。
"""

from __future__ import annotations

from enum import Enum


class AgeBand(str, Enum):
    """年齢分岐。0–2 は養護＋3つの視点、3–5 は養護＋5領域＋10の姿（枠組みが変わる）。"""

    零から二歳 = "0-2"
    三から五歳 = "3-5"


class Lineage(str, Enum):
    """記録系統。日誌は ①クラス日誌（全体的展開）②個別日誌（個の育ち）で分離して持つ（§10）。"""

    クラス日誌 = "class"
    個別日誌 = "individual"


class Certainty(str, Enum):
    """確度メタ。推論部分（特に欄名）を制度用語と断定しないために付与する（§10）。"""

    確証 = "confirmed"
    推論 = "inferred"
