"""表記ルール＝ひらがな表記DXの構造化辞書のスキーマ（pydantic）。

設計コンテキスト §5（決定的ロジック＝型/表記の保証）。保育書類には「子供→子ども」「友達→友だち」等の
表記の慣行があり、これを厳密に把握している保育士は少なく調べる余裕もない（現場ヒアリング 2026-07）。
本辞書を harness の正規化器（notation_store.normalize_*）が確定時に決定的に適用し、取りこぼしなく
表記を整える（＝「調べる余裕のない先生でも全員が助かる」）。**育つ指針カード（policy）が agentic な
"中身の勘所" であるのに対し、こちらは決定的な "表記の統一" ＝別の道具**（責務の線を混ぜない・§5）。

- NotationKind … ルールの種別（ひらがな化／表記統一／その他）。UI のグルーピング・ラベル用。
- NotationRule … 変換1件（pattern→replacement・種別・理由・有効/無効・日時）。
- NotationBook … ルール全体のストア（`knowledge/表記ルール.json` の正・version は楽観ロック用）。

スキーマは本パッケージに集約し、同じ関心事を別所で二重定義しない（規約: schemas/ 集約）。
clock は持たない＝`created_at`/`updated_at` は外部（web ルート境界）から注入する（純関数を保つ＝
policy スキーマ／finalize の日付解決と同じ流儀）。datetime は `model_dump(mode="json")`/`model_validate`
で JSON 往復する（harness/notation_store の load/save）。
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class NotationKind(str, Enum):
    """表記ルールの種別。UI のグルーピング・ラベルに使う（正規化の挙動は種別に依らず一律の置換）。"""

    ひらがな化 = "ひらがな化"  # 例: 子供→子ども・出来る→できる（保育の公用表記）
    表記統一 = "表記統一"  # 例: ゆれのある語を園の統一表記へ
    その他 = "その他"


class NotationRule(BaseModel):
    """表記の変換ルール1件＝pattern（変換元）を replacement（変換先）へ置き換える。

    正規化器は enabled な active ルールを**リテラル部分一致で決定的に置換**する（LLM を呼ばない）。
    誤変換の暴発は、正規化を叙述系フィールドに限定すること（notation_store）＋暴発するルールを
    保育士が enabled=False で止められることで抑える（silent lock はしない＝§5 の設計判断）。
    """

    id: str  # 決定的採番（notation_store.next_rule_id ＝ "rule-0001" 形式）
    pattern: str  # 変換元（空は add 時に弾く）
    replacement: str  # 変換先（ひらがな化で消す場合など空も許容）
    kind: NotationKind = NotationKind.ひらがな化
    note: str = ""  # なぜこの表記か（保育の公用表記・園の統一 等）
    enabled: bool = True  # 保育士が個別に無効化できる（暴発ルールを止める口）
    source: str = ""  # 由来（seed:初版 / 保育士の追加 等）
    created_at: datetime  # 外部注入（web ルート境界が now を載せる）
    updated_at: datetime  # 外部注入


class NotationBook(BaseModel):
    """表記ルールの全体ストア。`knowledge/表記ルール.json` の正（SSOT）。

    育つ指針（PolicyBook）と同じく book 丸ごと JSON 1行を SSOT とし、行へ射影しない
    （notation_store の DB 統合＝policy_books と同じ哲学）。version は楽観ロック用。
    """

    version: int = 1  # 将来のスキーマ移行用
    rules: list[NotationRule] = Field(default_factory=list)
