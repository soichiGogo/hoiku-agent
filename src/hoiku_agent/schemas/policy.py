"""育つ文書作成指針＝構造化カードのスキーマ（pydantic）。

設計コンテキスト §8（改善エージェント＝まわす本丸）/ §9（メモリ＝育つ指針）。v1 で指針の正(SSOT)を
markdown から **構造化カード(JSON)** へ移す。1カード＝指針の1項目（旧・見出し配下の箇条書き1行）。
改善エージェントが既存カードと**意味的競合**を精査し、競合があれば保育士に該当カードを提示して相談、
**保育士の決定で即反映**（add／supersede）する（番人＝意味的競合精査＋保育士決定・§8）。

- PolicyScope … カードの対象書類スコープ（共通／保育日誌／月案＝旧 markdown の3バケツに直対応）。
- PolicyStatus … カードの状態（active／superseded＝旧版／retired＝ソフト削除）。
- PolicyCard … 指針カード1枚（本文・由来・日時・supersede 関係・status）。
- PolicyChange … 変更履歴1件（だれの気づきで何が増えたか＝「回した証拠」）。
- PolicyBook … カード＋履歴の全体ストア（`knowledge/文書作成指針.json` の正）。

スキーマは本パッケージに集約し、同じ関心事を別所で二重定義しない（規約: schemas/ 集約）。
clock は持たない＝`created_at`/`updated_at`/`timestamp` は外部（improver の tool 境界）から注入する
（純関数を保つ＝finalize.py / FinalizeAgent の日付解決と同じ流儀）。datetime は `model_dump(mode="json")`/
`model_validate` で JSON 往復する（harness/policy_store の load/save）。
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class PolicyScope(str, Enum):
    """カードの対象書類スコープ。旧 markdown 指針の3バケツ（共通ルール／保育日誌／月案）に直対応。"""

    共通 = "共通"
    保育日誌 = "保育日誌"
    月案 = "月案"


class PolicyStatus(str, Enum):
    """カードの状態。supersede（置換）は旧カードを残して履歴を保つ（「回した証拠」＝§8）。"""

    active = "active"  # 現行（read_policy / UI が表示する）
    superseded = "superseded"  # 新カードに置き換えられた旧版（履歴として残す）
    retired = "retired"  # ソフト削除（参照されない）


class PolicyChangeAction(str, Enum):
    """変更履歴のアクション種別。"""

    add = "add"
    supersede = "supersede"
    remove = "remove"


class PolicyCard(BaseModel):
    """指針カード1枚＝指針の構造化単位（旧・見出し配下の箇条書き1項目）。

    改善エージェントが提案し、保育士の決定で即反映される。supersede 時は旧カード（status=superseded）を
    残したまま新カード（status=active・supersedes=旧id）を足す＝版管理で「回した証拠」を保つ（§8）。
    """

    id: str  # 決定的採番（policy_store.next_card_id ＝ "card-0001" 形式）
    scope: PolicyScope
    body: str  # カード本文（旧・箇条書き本文）。空は add 時に弾く
    rationale: str = ""  # なぜこの勘所か（指針整合・園ルール 等）
    source: str = ""  # 由来＝だれの気づきか（保育士の修正メモ / session / "seed:初版" 等）
    status: PolicyStatus = PolicyStatus.active
    supersedes: str | None = None  # この新カードが置き換えた旧カードの id
    superseded_by: str | None = None  # この旧カードを置き換えた新カードの id
    created_at: datetime  # 外部注入（tool 境界が now を載せる）
    updated_at: datetime  # 外部注入


class PolicyChange(BaseModel):
    """変更履歴1件＝「回した証拠」（いつ・だれの気づきで・何が無矛盾に増えたか）。"""

    timestamp: datetime  # 外部注入（= 関与カードの created_at）
    action: PolicyChangeAction
    card_id: str  # 影響した（新）カードの id
    superseded_id: str | None = None  # supersede 時の旧カード id
    summary: str = ""  # 何を変えたか（人間可読）
    source: str = ""  # だれの気づきか（card.source と同源）
    decided_by: str = "保育士"  # 舵は保育士（即反映の決定者）


class PolicyBook(BaseModel):
    """カード＋履歴の全体ストア。`knowledge/文書作成指針.json` の正（SSOT）。"""

    version: int = 1  # 将来のスキーマ移行用
    cards: list[PolicyCard] = Field(default_factory=list)
    history: list[PolicyChange] = Field(default_factory=list)
