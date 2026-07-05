"""クラス月案（園の実様式＝月間指導計画）のスキーマ（pydantic）。

設計コンテキスト §10（月案：フィールド×依存元）/ §18（園の実様式）。既存の個別月案（MonthlyPlan・
child_id 単位）と対称に、**園が実際に使うクラス月案フォーム**（`web/templates/monthly_0_2.docx` /
`monthly_3_5.docx`）の欄構成そのものを型にした doc_type。個別月案が「1人の子の月次計画」なのに対し、
クラス月案は**クラス全体の月次計画**で、園の帳票様式がこの形（区分×領域グリッド＋0–2 のみ個人目標小表）。

様式は非線形の構造様式（児童票の年間マトリクスと同じく template_store の線形セクション列には載せない）。
行・欄の定義（GRID_ROWS）はこのモジュールに1つ置き、テキスト整形（draft.py）・帳票PDF（chohyo_pdf）・
Word 流し込み（docx_fill）・編集フォーム（docedit.js）が共有する（レイアウトの二重管理を避ける・§18）。

年齢分岐について：園の実様式は 0–2/3–5 とも**区分×領域グリッドは同一の7行**（養護2本柱＋教育5領域）で、
0–2 のみ「個人目標（月齢・一人ひとりに応じて）」小表を持つ。したがってアプリの 0–2＝3つの視点/3–5＝5領域の
タグ分岐は**この書類では適用しない**（様式が全年齢で5領域グリッドのため）。年齢帯は帳票のタイトルと個人目標
小表の出し分けにのみ効く。

評価系欄（保育者の評価／子どもの評価／気になる子どもへの対応／個人目標の評価・反省）は月末に保育士が
記入する運用欄＝**AI 非生成**（原簿系の身長体重と同じ扱い）。担任・園長・主任・クラス名は手書き相当の
任意メタ。実名は書かない（架空児の仮名のみ＝§14）。
"""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, BeforeValidator, Field, model_validator

from .enums import AgeBand

# author が null / 省略で送っても parse を落とさず空文字へ寄せる自由記述 str（document.py と同型）。
_BlankableStr = Annotated[str, BeforeValidator(lambda v: "" if v is None else v)]

# 区分×領域グリッドの正準行（園フォームの表と同順・§18）。養護2本柱＋教育5領域＝全年齢で共通。
# (区分, 領域) の並びがそのまま帳票・フォーム・テキストの行順になる（レイアウトのデータはここに1つ）。
GRID_ROWS: list[tuple[str, str]] = [
    ("養護", "生命の保持"),
    ("養護", "情緒の安定"),
    ("教育", "健康"),
    ("教育", "人間関係"),
    ("教育", "環境"),
    ("教育", "言葉"),
    ("教育", "表現"),
]
# 領域→区分（正準化で category を決定的に補完するため）。
_CATEGORY_OF = {domain: category for category, domain in GRID_ROWS}


class ClassPlanRow(BaseModel):
    """区分×領域グリッドの1行（園フォームの「区分｜領域｜ねらい｜環境・構成｜子どもの姿｜援助・配慮」）。

    category（区分）・domain（領域）は GRID_ROWS 由来の機械メタ（正準化で決定的に補完＝AI の取り違えを
    型で防ぐ）。内容4欄（ねらい／環境・構成／子どもの姿／援助・配慮）が AI 生成の対象。
    """

    category: _BlankableStr = ""  # 区分（養護/教育）＝正準化で補完
    domain: _BlankableStr = ""  # 領域（生命の保持/情緒の安定/健康/…）＝行の同定キー
    aim: _BlankableStr = ""  # ねらい
    environment: _BlankableStr = ""  # 環境・構成
    child_state: _BlankableStr = ""  # 子どもの姿
    support: _BlankableStr = ""  # 援助・配慮


class IndividualGoal(BaseModel):
    """0–2 の「個人目標（月齢・一人ひとりに応じて）」小表の1行（園フォーム＝0–2 のみ存在）。

    前月日誌の登場児それぞれについて、子どもの姿とねらい・配慮を書く。評価・反省は月末に保育士が
    記入する運用欄＝AI 非生成。
    """

    child_id: str  # 架空児のみ（§14）
    age_months: _BlankableStr = ""  # 月齢（◯歳◯か月・任意）
    child_state: _BlankableStr = ""  # 子どもの姿
    aim_support: _BlankableStr = ""  # ねらい・配慮
    evaluation: _BlankableStr = ""  # 評価・反省（AI 非生成・月末記入）


class ClassMonthlyPlan(BaseModel):
    """クラス月案（月間指導計画・クラス単位・全年齢）。write_class_monthly_draft の出力型 /
    validate_class_monthly_fields の入力契約（§10/§18）。

    園の実様式（monthly_*.docx）の欄構成そのもの。前月日誌の集積（L2 還流）を「先月の子どもの姿」と
    区分×領域グリッド・0–2 の個人目標へ流す。grid は正準7行（GRID_ROWS）に model_validator で
    決定的にそろえる（AI が行を欠く/並べ替えても帳票・フォームが常に7行で描ける＝型の保証）。
    """

    month: str = Field(description="対象月（YYYY-MM）")
    age_band: AgeBand
    class_name: _BlankableStr = Field(
        default="", description="クラス名（例: ひよこ組・任意・手書き相当）"
    )
    # ── 上部の単欄（園フォーム table[1]） ──
    monthly_goal: str = Field(description="今月の保育目標（クラス全体のねらい）")
    prev_month_state: str = Field(description="先月の子どもの姿（前月日誌の集積＝L2 還流に依存）")
    events: _BlankableStr = Field(default="", description="今月の行事（任意）")
    parent_support: _BlankableStr = Field(default="", description="保護者支援（任意）")
    # ── 区分×領域グリッド（園フォーム table[2]・正準7行） ──
    grid: list[ClassPlanRow] = Field(
        default_factory=list,
        description="区分×領域グリッド（養護2本柱＋教育5領域＝GRID_ROWS の7行）",
    )
    # ── 下部の連携欄（園フォーム table[3]・2×2） ──
    syokuiku: _BlankableStr = Field(default="", description="食育（任意）")
    health_safety: _BlankableStr = Field(default="", description="健康・安全（任意）")
    family_liaison: _BlankableStr = Field(default="", description="家庭との連携（任意）")
    staff_liaison: _BlankableStr = Field(default="", description="職員間の連携（任意）")
    # ── 個人目標小表（0–2 のみ・園フォーム table[4]） ──
    individual_goals: list[IndividualGoal] = Field(
        default_factory=list,
        description="個人目標（月齢・一人ひとりに応じて）。0–2 のみ＝前月日誌の登場児ごと",
    )
    # ── 評価系欄（月末に保育士が記入する運用欄＝AI 非生成） ──
    teacher_evaluation: _BlankableStr = Field(
        default="", description="保育者の評価（月末記入・AI 非生成）"
    )
    children_evaluation: _BlankableStr = Field(
        default="", description="子どもの評価（月末記入・AI 非生成）"
    )
    notable_children: _BlankableStr = Field(
        default="", description="気になる子どもへの対応（月末記入・AI 非生成）"
    )

    @model_validator(mode="after")
    def _canonicalize_grid(self) -> ClassMonthlyPlan:
        """grid を GRID_ROWS の正準7行に決定的にそろえる（欠落は空行で補完・区分は領域から補完・§18）。

        AI が行を欠いたり並べ替えたり区分を取り違えても、帳票・編集フォーム・テキスト整形が常に
        「養護2本柱＋教育5領域」の7行を同順で描けるようにする（型の保証＝§5）。領域名で AI の行を
        引き当て、内容4欄を写す（同一領域が複数来たら先勝ち・GRID_ROWS に無い領域は落とす）。
        """
        by_domain: dict[str, ClassPlanRow] = {}
        for row in self.grid:
            key = (row.domain or "").strip()
            if key in _CATEGORY_OF and key not in by_domain:
                by_domain[key] = row
        canonical: list[ClassPlanRow] = []
        for category, domain in GRID_ROWS:
            src = by_domain.get(domain)
            canonical.append(
                ClassPlanRow(
                    category=category,
                    domain=domain,
                    aim=src.aim if src else "",
                    environment=src.environment if src else "",
                    child_state=src.child_state if src else "",
                    support=src.support if src else "",
                )
            )
        self.grid = canonical
        return self
