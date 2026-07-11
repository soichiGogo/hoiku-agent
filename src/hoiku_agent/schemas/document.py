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
from typing import Annotated

from pydantic import BaseModel, BeforeValidator, Field

from .domain import FiveDomains, TenNoSugata, ThreeViewpoint
from .enums import AgeBand

# author が null / 省略で送っても parse を落とさず空文字へ寄せる自由記述 str。欠落そのものは
# validate_fields が「未記入」として不足リストに報告する＝ハードクラッシュさせず「型は成立・中身は不足」
# として可視化する設計意図に整合（§10 / harness/schema_check）。weather のような必須自由記述に使う。
_BlankableStr = Annotated[str, BeforeValidator(lambda v: "" if v is None else v)]


def _canonical_month(v: object) -> object:
    """対象月をゼロ詰め "YYYY-MM" に正規化する（"2026-7" → "2026-07"）。

    月案・クラス月案の集積は month の**辞書順**を時系列前提にする（aggregate.class_plan_history_digest の
    月順ソート・record_store の `target_month < before_month` 比較・dedupe_key）。LLM が非ゼロ詰めで echo
    しても canonical に寄せ、全経路（author 出力／編集保存／archive JSON の再検証）で entry.month を
    一貫させる。解釈不能な値・None・非文字列は素通し（schema_check が形式不備として可視化＝ハードクラッシュ
    させない・型の成立判定は schema_check の責務＝§5/§10）。"""
    if not isinstance(v, str):
        return v
    y_s, sep, m_s = v.strip().partition("-")
    if sep and y_s.isdigit() and m_s.isdigit() and 1 <= int(m_s) <= 12:
        return f"{int(y_s):04d}-{int(m_s):02d}"
    return v.strip()


# 対象月（YYYY-MM）＝ゼロ詰め正規化を通す str（月案・クラス月案で共用＝二重定義しない）。
MonthStr = Annotated[str, BeforeValidator(_canonical_month)]


class DocumentType(str, Enum):
    """対象書類。国が課す必須文書を土台に対象を絞る（§2/§3）。第1号は 月案・保育日誌。

    保育経過記録は §19（ヒアリング反映 2026-07）で追加：日誌の期間集積を再構成する下流文書（L3）。
    保育要録は §19 が予告した集積階層（日誌→月案→保育経過記録→要録）の最終段（L4）＝最終年度（年長）の
    保育経過記録を集積し小学校へ引き継ぐ書類。年一回・年長のみだが一人あたりの労力が最重量。
    """

    年間計画 = "年間計画"
    月案 = "月案"
    週案 = "週案"
    日案 = "日案"
    連絡帳 = "連絡帳"
    お便り = "お便り"
    保育日誌 = "保育日誌"
    保育経過記録 = "保育経過記録"
    保育要録 = "保育要録"
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


class LifeRecord(BaseModel):
    """0–2 個別の生活記録（養護＝生命の保持の中核）。標準様式調査（川口市等の自治体様式）では、
    0–2 日誌は児ごとに食事・睡眠・排泄・機嫌/体調（視診）を記録するのが標準（§10）。各欄は空可で、
    validate_fields が「4 欄すべて空＝生活記録が未記入」を1件報告する（1欄でも記入があれば型成立）。
    """

    meal: _BlankableStr = ""  # 食事（授乳・離乳食・量）
    sleep: _BlankableStr = ""  # 睡眠（午睡時間・寝つき）
    toilet: _BlankableStr = ""  # 排泄
    mood_health: _BlankableStr = ""  # 機嫌・体調・視診

    def is_blank(self) -> bool:
        """4 欄すべてが空（未記入）か。validate_fields の「生活記録が未記入」判定に使う。"""
        return not any(v.strip() for v in (self.meal, self.sleep, self.toilet, self.mood_health))


class IndividualNote(BaseModel):
    """個別日誌（特記事項／個人記録）。0–2 個別の本体（§10・個別日誌系統）。"""

    child_id: str
    # 月齢（◯歳◯か月・任意）。0–2 は月齢で発達を見るが、架空児は生年月日が無く自動導出できないため
    # 保育士が編集する自由記述（必須化しない・LLM が文脈/メモリから補ってもよい）。
    age_months: _BlankableStr = ""
    observed_state: _BlankableStr = (
        ""  # 当日の観察＝子どもの姿（空は validate_fields が未記入で報告）
    )
    # タグ要件は年齢で分岐（0–2＝ThreeViewpoint / 3–5＝FiveDomains）。分岐の強制は validate_fields。
    tags: list[TenNoSugata | ThreeViewpoint | FiveDomains] = Field(default_factory=list)
    # 0–2 養護の中核＝個別の生活記録（食事・睡眠・排泄・機嫌/体調）。validate_fields が存在を要求する。
    life_record: LifeRecord = Field(default_factory=LifeRecord)
    individual_aim: _BlankableStr = Field(
        default="", description="個人のねらい（任意・個別指導計画と連動）"
    )


class DiaryEvaluation(BaseModel):
    """評価・反省は必ず2視点を別フィールドで必須にする（§10）。両系統にまたがる。"""

    child_focus: _BlankableStr = Field(default="", description="(a)子どもに焦点を当てた振り返り")
    self_review: _BlankableStr = Field(
        default="", description="(b)自分のねらい・内容・環境構成・関わりの適否"
    )


class DiaryEntry(BaseModel):
    """保育日誌（日次）。write_draft の出力型 / validate_fields の入力契約（§10）。

    欄名は越谷市様式等からの推論を含む（§10）。園差で拡張されうるため拡張可能に保つ。
    """

    date: date
    age_band: AgeBand
    weather: _BlankableStr = (
        ""  # 必須欄。空/None は validate_fields が「天候が未記入」で報告（クラッシュさせない）
    )
    # 気温・組名は 0–2 標準様式のヘッダにある任意欄（園差・§10）。天候と対で持ち、必須化しない
    # （validate は要求しない）。空可＝保育士が編集フォームで補える／LLM が観察メモから補ってもよい。
    temperature: _BlankableStr = ""  # 気温（例: 26℃・任意）。天候と対で標準様式ヘッダに置く
    class_name: _BlankableStr = (
        ""  # 組名（例: ひよこ組・任意）。園様式は個別記録でも組名を持つことが多い
    )
    daily_aim: _BlankableStr = Field(
        default="",
        description="本日のねらい（養護面・教育面。日案←週案←月案と連動・任意・標準様式）",
    )
    attendance: list[ChildAttendance]  # クラス日誌
    health_notes: str | None = None  # クラス日誌
    practice_record: _BlankableStr = Field(  # クラス日誌（←日案←週案←月案ねらいにトップダウン一貫）
        default="", description="保育の実践記録。日案←週案←月案のねらいにトップダウン一貫"
    )
    individual_notes: list[IndividualNote]  # 個別日誌（0–2 個別の本体）
    evaluation: DiaryEvaluation  # 両系統・2視点必須
    parent_contact: str | None = None  # クラス日誌


# ──────────────────────────── 月案 v0（0–2 個別月案） ────────────────────────────
# 設計コンテキスト §3「月案は日誌の集積に乗せる」/ §4「L2 月次PDCA」/ §10「月案：フィールド×依存元」。
# 0–2 は個別計画が基本（§3）＝個別月案（child_id 単位）。前月日誌の集積（L2 還流）を「前月の子どもの姿」
# 「評価・反省」へ流す。欄名は告示・自治体様式からの推論を含む（§10 / 制度用語と断定しない）。


class MonthlyEducationNote(BaseModel):
    """月案「教育」のねらい・内容（年齢分岐タグ付き）。0–2＝3つの視点 / 3–5＝5領域（§10）。

    養護（生命の保持・情緒の安定）は MonthlyPlan.nurturing_life / nurturing_emotion に分離して持つ。ここは「教育」側で、
    年齢で枠組みが変わる（0–2＝3つの視点・3–5＝5領域・§10）ため個別記録と同型のタグ要件を課す。
    """

    aim: str = Field(description="教育のねらい・内容（今月）")
    # タグ要件は年齢で分岐（0–2＝ThreeViewpoint / 3–5＝FiveDomains）。強制は validate_monthly_fields。
    tags: list[ThreeViewpoint | FiveDomains | TenNoSugata] = Field(default_factory=list)


class MonthlyPlan(BaseModel):
    """個別月案（月次）。write_monthly_draft の出力型 / validate_monthly_fields の入力契約（§10）。

    第1号は 0–2 個別＝個別月案（child_id 単位・§3）。前月日誌の月集積（L2 還流＝harness/aggregate）を
    「前月の子どもの姿」「評価・反省」へ流す（§4/§10）。欄名は推論を含む（§10）。園差で拡張可能に保つ。
    """

    month: MonthStr = Field(description="対象月（YYYY-MM・ゼロ詰め正規化）")
    age_band: AgeBand
    child_id: str  # 架空児のみ（§14）。0–2 個別＝個別月案
    # 月齢（◯歳◯か月・任意）。0–2 は月齢で発達を見るが架空児は生年月日が無く自動導出不可＝保育士編集。
    age_months: _BlankableStr = ""
    prev_child_state: str = Field(
        description="前月の子どもの姿（前月日誌の集積＋前月評価反省に依存＝L2 還流・§10）"
    )
    # 養護2本柱は0–2標準様式で「生命の保持」「情緒の安定」を必ず分けて持つ（§10・標準様式調査）。
    nurturing_life: str = Field(
        description="養護：生命の保持（安全・健康・生理的欲求の充足）。年齢に依らず必須＝§10"
    )
    nurturing_emotion: str = Field(
        description="養護：情緒の安定（応答的関わり・信頼関係・愛着形成）。年齢に依らず必須＝§10"
    )
    education: list[MonthlyEducationNote] = Field(
        description="教育のねらい・内容（年齢分岐タグ必須＝0–2は3つの視点/3–5は5領域・§10）"
    )
    monthly_goals: str = Field(
        description="今月のねらい・内容（記録された姿の理解→ねらいへの変換＝勘所・§10）"
    )
    environment_support: str = Field(
        description="環境構成・援助（配慮）。ねらい／過去月案・園ルールに依存"
    )
    events_family_food: str | None = Field(
        default=None, description="行事／家庭連携／食育・健康（様式で実在・園差で拡張＝§10）"
    )
    evaluation_reflection: str = Field(
        description="評価・反省（当月日誌の集積と予想ねらいの照合＝「回す」の起点・双方向・§10）"
    )


# ──────────────────────── 保育経過記録（期ごと・全年齢） ────────────────────────
# §19（ヒアリング反映 2026-07）：保育経過記録の実体は3層（①原簿＝静的台帳／②発達チェックリスト／
# ③期ごとの叙述式「保育経過記録」）で、AI 生成対象は③のみ（①②はフォーム＝AI外）。
# 共通構造（越谷市公式様式・実務解説で裏取り）＝「期の区切り × 領域別の叙述 × 配慮・特記 ×
# 総合所見 × 確認印」。日誌の期間集積（L3 還流＝L2 の期間版）に乗せて書く。欄名は自治体様式からの
# 推論を含む（制度用語と断定しない＝§10 / Certainty）。園差（期制・枠組み）で拡張可能に保つ。


class DevelopmentNote(BaseModel):
    """保育経過記録「発達の経過」の領域別叙述1件（年齢分岐タグ付き）。MonthlyEducationNote と同型。

    タグ要件は年齢で分岐（0–2＝ThreeViewpoint / 3–5＝FiveDomains・実務主流＝0歳:3つの視点/
    全年齢:5領域と一致）。強制は validate_child_record_fields（実体は harness の _required_tag_type）。
    """

    description: str = Field(description="その期の子どもの発達・生活の経過（叙述）")
    tags: list[ThreeViewpoint | FiveDomains | TenNoSugata] = Field(default_factory=list)


class ChildRecord(BaseModel):
    """保育経過記録（期ごと）（児童別・全年齢）。write_child_record_draft の出力型 /
    validate_child_record_fields の入力契約（§19）。

    fetch_reference で取得した期間日誌（L3 還流）を「発達の経過」「総合所見」へ流す。
    保護者の開示請求で開示され得る書類＝断定的・否定的表現を避ける（表現の点検はレビューAI／
    ここは型のみ）。期の区切り（月次/3期/4期制）は園差＝呼び出し側が seed する期間で表現し、
    期制の設定化は残課題（§18 と同じ現場依存）。
    """

    period: str = Field(description="対象期間（例: 2026-04〜2026-06。期制は園差＝自由記述）")
    age_band: AgeBand
    child_id: str  # 架空児のみ。実名は書かない（§14）
    # 月齢/年齢（◯歳◯か月・任意）。児童マスタに生年月日が登録済みなら finalize/帳票の web 境界が
    # 期末（記入時点）の満年齢を決定的に充填する（`record_store.age_months_label`）。未登録（架空児・
    # デモ含む）は従来どおり保育士編集の自由記述にフォールバックする（§14）。
    age_months: _BlankableStr = ""
    development_notes: list[DevelopmentNote] = Field(
        description="発達の経過（領域別叙述・年齢分岐タグ必須＝0–2は3つの視点/3–5は5領域・§19）"
    )
    care_notes: _BlankableStr = Field(
        default="", description="配慮事項・特記（個別配慮・医療的ケアの経過など。任意・園差で拡張）"
    )
    family_liaison: _BlankableStr = Field(
        default="", description="家庭との連携（保護者とのやりとり・園と家庭の育ちの共有。任意）"
    )
    overall_note: str = Field(
        description="総合所見（その期の育ちの総括。開示前提＝肯定的・非断定的に書く）"
    )
    next_aims: _BlankableStr = Field(
        default="", description="次期に向けて（課題・ねらいへの橋渡し。任意）"
    )
    # 身体測定（原簿系＝実様式の年間マトリクスに枠がある）。**LLM は生成しない**（測定値の創作禁止）＝
    # 保育士が編集フォームで記入するか、帳票の空欄に手書きする。任意・validate も要求しない。
    height_cm: _BlankableStr = Field(
        default="", description="身長（例: 78.5。任意・原簿系＝保育士記入。AI は創作しない）"
    )
    weight_kg: _BlankableStr = Field(
        default="", description="体重（例: 10.2。任意・原簿系＝保育士記入。AI は創作しない）"
    )


# ──────────────────── 保育要録（保育所児童保育要録・年長・L4） ────────────────────
# §19 が予告した集積階層（日誌→月案→保育経過記録→要録）の最終段。全国統一様式（こども家庭庁）で、
# 実体は2部構成：「入所に関する記録」（氏名・就学先・保育期間 等＝原簿系フォーム＝AI外）と
# 「保育に関する記録」（叙述部＝AI生成対象）。生成対象は後者のみ。共通構造（様式の参考例で裏取り）＝
# 「最終年度の重点（クラス全体）× 個人の重点 × 保育の展開と子どもの育ち（5領域＋10の姿）×
# 特に配慮すべき事項 × 最終年度に至るまでの育ち（入所〜前年度）」。年長（5歳児）専用＝常に5領域。
# 開示前提（小学校へ引き継ぐ・保護者開示請求で開示され得る）＝断定的/否定的表現を避ける（表現の
# 点検はレビューAI／ここは型のみ）。最終年度の保育経過記録の集積（L4 還流）に乗せて書く。欄名は自治体
# 様式・実務解説からの推論を含む（制度用語と断定しない＝§10 / Certainty）。園差で拡張可能に保つ。


class NurseryRecord(BaseModel):
    """保育要録＝保育所児童保育要録の「保育に関する記録」（児童別・年長）。
    write_nursery_record_draft の出力型 / validate_nursery_record_fields の入力契約（§19・L4）。

    fetch_reference で取得した保育経過記録（L4 還流）を「保育の展開と子どもの育ち」
    「個人の重点」へ流し、入所〜前年度の育ちは recall_child_history／過去年度の保育経過記録から
    「最終年度に至るまでの育ち」へ叙述する。年長（5歳児）専用のため age_band は常に 三から五歳
    （＝5領域）。就学先・保育期間など「入所に関する記録」は原簿系＝AI 生成しない任意欄（保育経過記録の
    身体測定と同じ扱い＝保育士が編集フォームで記入）。
    """

    fiscal_year: str = Field(description="対象年度（例: 2026 / 令和8年度。園差＝自由記述）")
    age_band: AgeBand  # 年長（5歳児）＝三から五歳を想定（5領域）。0–2 要録は制度上存在しない
    child_id: str  # 架空児のみ。実名は書かない（§14）
    # 月齢/年齢（◯歳◯か月・任意）。架空児は生年月日が無く自動導出できないため保育士編集の自由記述。
    age_months: _BlankableStr = ""
    final_year_focus: str = Field(
        description="最終年度の重点（年長クラス全体の年間目標・ねらい＝年度当初に設定した重点）"
    )
    individual_focus: str = Field(
        description="個人の重点（1年を振り返り、その子の指導で特に重視してきた点）"
    )
    development_notes: list[DevelopmentNote] = Field(
        description="保育の展開と子どもの育ち（成長の著しい点を5領域＋10の姿の視点で叙述・"
        "年齢分岐タグ必須＝年長は5領域・§19）。DevelopmentNote を保育経過記録と共用"
    )
    special_notes: _BlankableStr = Field(
        default="", description="特に配慮すべき事項（就学支援等。無ければ空＝様式上「なし」・任意）"
    )
    growth_until_final: str = Field(
        description="最終年度に至るまでの育ちに関する事項（入所時〜前年度の育ちの経過。最終年度の"
        "姿を理解するうえで特に重要な点に絞る＝開示前提で肯定的・非断定的に）"
    )
    # 「入所に関する記録」の一部（原簿系＝実様式のヘッダに枠がある）。**LLM は生成しない**（創作禁止）＝
    # 保育士が編集フォームで記入するか帳票の空欄に手書きする。任意・validate も要求しない。
    school_name: _BlankableStr = Field(
        default="", description="就学先の小学校名（任意・原簿系＝保育士記入。AI は創作しない）"
    )
    enrollment_period: _BlankableStr = Field(
        default="", description="保育期間（入所〜卒所。任意・原簿系＝保育士記入。AI は創作しない）"
    )
