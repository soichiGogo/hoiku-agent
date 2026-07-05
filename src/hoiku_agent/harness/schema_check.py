"""harness：必須欄の充足・年齢分岐チェック（決定的）。

設計コンテキスト §5/§10。validate_fields の "実体" はここに1つだけ置く。tools/validate_fields.py
は FunctionTool としてこれを呼ぶ薄いラッパに留める（二重実装しない＝§5/§6）。

年齢分岐は必須（§10）：
- 0–2（AgeBand.零から二歳） … 個別 note のタグ要件＝ThreeViewpoint（3つの視点）。
- 3–5（AgeBand.三から五歳） … 個別 note のタグ要件＝FiveDomains（5領域）。
評価・反省は2視点（child_focus / self_review）が必須（§10・DiaryEvaluation で型担保済）。
ここでは2視点が "空文字でない" ことまで踏み込んで充足を見る。

「型」としての成立だけを決定的に検査する（中身の良し悪し＝レビューAI／指針整合＝eval の責務）。
越谷市様式末尾「など」＝園差で拡張されうるため、未知の追加欄は弾かない（拡張に寛容）。

LLM は呼ばない。判定は純粋関数で、tests/test_harness/ から LLM 非依存・高速に検証できる。
"""

from __future__ import annotations

from ..schemas import (
    AgeBand,
    ChildRecord,
    ClassMonthlyPlan,
    DiaryEntry,
    FiveDomains,
    MonthlyPlan,
    NurseryRecord,
    ThreeViewpoint,
)


def _required_tag_type(age_band: AgeBand) -> tuple[type, str]:
    """年齢分岐の必須タグ体系を返す（0–2＝3つの視点 / 3–5＝5領域・§10）。

    日誌（個別記録）と月案（教育のねらい）で同じ分岐を使うため、決定ロジックの実体をここに1つ置く
    （二重実装しない＝§5）。返り値は (Enum 型, 表示ラベル)。
    """
    if age_band is AgeBand.零から二歳:
        return ThreeViewpoint, "3つの視点（ThreeViewpoint）"
    return FiveDomains, "5領域（FiveDomains）"


def validate_fields(entry: DiaryEntry) -> list[str]:
    """日誌ドラフトの必須欄・年齢分岐を検査し、違反メッセージの一覧を返す（空＝充足）。

    Args:
        entry: 検査対象の日誌ドラフト（DiaryEntry）。

    Returns:
        違反メッセージのリスト。空リストなら "型" として成立。

    検査内容（§10）:
    - 必須欄が空でないこと（天候・実践記録・個別記録・評価反省2視点）。
    - 年齢分岐タグ要件：0–2＝ThreeViewpoint / 3–5＝FiveDomains を各個別記録が1つ以上持つこと。
    - 各個別記録に「子どもの姿（observed_state）」が記入されていること。
    """
    problems: list[str] = []

    # ── 必須欄の充足（空文字も "未記入" 扱い） ──
    if not entry.weather.strip():
        problems.append("天候が未記入")
    if not entry.practice_record.strip():
        problems.append("保育の実践記録が未記入")
    if not entry.individual_notes:
        problems.append("個別日誌（individual_notes）が空：個の記録が日誌の本体（§3/§10）")
    if not entry.evaluation.child_focus.strip():
        problems.append("評価・反省(a 子どもに焦点)が未記入（2視点必須＝§10）")
    if not entry.evaluation.self_review.strip():
        problems.append("評価・反省(b 自分の保育の適否)が未記入（2視点必須＝§10）")

    # ── 年齢分岐：要求するタグ体系を決める（0–2＝3つの視点 / 3–5＝5領域） ──
    required_tag_type, tag_label = _required_tag_type(entry.age_band)

    # ── 個別記録ごとの内容＋年齢分岐タグ ──
    for note in entry.individual_notes:
        if not note.observed_state.strip():
            problems.append(f"child_id={note.child_id}: 子どもの姿（observed_state）が未記入")
        if not any(isinstance(t, required_tag_type) for t in note.tags):
            problems.append(
                f"child_id={note.child_id}: {entry.age_band.value} は{tag_label}のタグが1つ以上必要"
            )
        # 0–2 養護の中核＝個別の生活記録（食事・睡眠・排泄・機嫌/体調）。4 欄すべて空なら未記入扱い
        # （1欄でも記入があれば型成立。標準様式調査＝§10）。**0–2 のみ必須**：3–5 の標準様式に
        # 児別の生活記録欄は無いため課さない（全年齢対応＝§19。記入があれば整形には出す）。
        if entry.age_band is AgeBand.零から二歳 and note.life_record.is_blank():
            problems.append(
                f"child_id={note.child_id}: 生活記録（食事・睡眠・排泄・機嫌/体調）が未記入"
                "（0–2 養護の中核＝§10）"
            )

    return problems


def validate_monthly_fields(plan: MonthlyPlan) -> list[str]:
    """個別月案ドラフトの必須欄・年齢分岐を検査し、違反メッセージの一覧を返す（空＝充足・§10）。

    日誌（validate_fields）と同じく「型としての成立」だけを決定的に検査する（中身の良し悪し＝
    レビューAI／指針整合＝eval の責務）。年齢分岐は日誌と共通の _required_tag_type を使い、
    月案では「教育のねらい（education）」に 0–2＝3つの視点 / 3–5＝5領域 のタグを課す（§10）。

    Args:
        plan: 検査対象の月案ドラフト（MonthlyPlan）。

    Returns:
        違反メッセージのリスト。空リストなら "型" として成立。
    """
    problems: list[str] = []

    # ── 必須欄の充足（空文字も "未記入" 扱い） ── §10 月案：フィールド×依存元
    if not plan.month.strip():
        problems.append("対象月（month）が未記入")
    if not plan.prev_child_state.strip():
        problems.append("前月の子どもの姿が未記入（L2 還流の入力＝§10）")
    if not plan.nurturing_life.strip():
        problems.append("養護：生命の保持が未記入（0–2 は養護2本柱を分ける＝§10）")
    if not plan.nurturing_emotion.strip():
        problems.append("養護：情緒の安定が未記入（0–2 は養護2本柱を分ける＝§10）")
    if not plan.monthly_goals.strip():
        problems.append("今月のねらい・内容が未記入（§10）")
    if not plan.environment_support.strip():
        problems.append("環境構成・援助（配慮）が未記入（§10）")
    if not plan.evaluation_reflection.strip():
        problems.append("評価・反省が未記入（「回す」の起点＝§10）")
    if not plan.education:
        problems.append("教育のねらい（education）が空：年齢分岐タグ付きで1つ以上必要（§10）")

    # ── 年齢分岐：教育のねらいに必須タグ体系を課す（0–2＝3つの視点 / 3–5＝5領域） ──
    required_tag_type, tag_label = _required_tag_type(plan.age_band)
    for i, note in enumerate(plan.education):
        if not note.aim.strip():
            problems.append(f"教育のねらい[{i}]: 内容（aim）が未記入")
        if not any(isinstance(t, required_tag_type) for t in note.tags):
            problems.append(
                f"教育のねらい[{i}]: {plan.age_band.value} は{tag_label}のタグが1つ以上必要"
            )

    return problems


def validate_class_monthly_fields(plan: ClassMonthlyPlan) -> list[str]:
    """クラス月案（園の実様式）ドラフトの必須欄を検査し、違反メッセージの一覧を返す（空＝充足・§18）。

    個別月案（validate_monthly_fields）と違い、園の実様式は 0–2/3–5 とも**区分×領域グリッドが同一の
    7行**（養護2本柱＋教育5領域）なので、3つの視点/5領域のタグ分岐は課さない（様式が全年齢で5領域
    グリッドのため＝§18）。grid はスキーマの model_validator が正準7行にそろえ済み＝ここでは各行の
    「ねらい（aim）」の充足（月案の核）を見る。個人目標小表は **0–2 のみ**（園フォームに 0–2 だけ存在）で
    1件以上を要求し、各件に子どもの姿・ねらい・配慮を求める（3–5 は課さない）。評価系欄は月末記入＝
    AI 非生成なので検査しない（未記入は不備でない）。

    Args:
        plan: 検査対象のクラス月案ドラフト（ClassMonthlyPlan）。

    Returns:
        違反メッセージのリスト。空リストなら "型" として成立。
    """
    problems: list[str] = []

    # ── 必須欄の充足（空文字も "未記入" 扱い） ──
    if not plan.month.strip():
        problems.append("対象月（month）が未記入")
    if not plan.monthly_goal.strip():
        problems.append("今月の保育目標が未記入（クラス全体のねらい＝§18）")
    if not plan.prev_month_state.strip():
        problems.append("先月の子どもの姿が未記入（L2 還流の入力＝§18）")

    # ── 区分×領域グリッド（正準7行）：各行のねらい（aim）を必須にする ──
    for row in plan.grid:
        if not row.aim.strip():
            problems.append(f"{row.category}「{row.domain}」のねらいが未記入（グリッド＝§18）")

    # ── 個人目標小表：0–2 のみ必須（園フォームに 0–2 だけ存在・全年齢対応＝§18） ──
    if plan.age_band is AgeBand.零から二歳:
        if not plan.individual_goals:
            problems.append(
                "個人目標（月齢・一人ひとりに応じて）が空：0–2 は前月日誌の登場児ごとに1件以上必要（§18）"
            )
        for i, goal in enumerate(plan.individual_goals):
            if not goal.child_id.strip():
                problems.append(f"個人目標[{i}]: 対象児（child_id）が未記入")
            if not goal.child_state.strip():
                problems.append(f"個人目標[{i}]: 子どもの姿が未記入")
            if not goal.aim_support.strip():
                problems.append(f"個人目標[{i}]: ねらい・配慮が未記入")

    return problems


def validate_child_record_fields(record: ChildRecord) -> list[str]:
    """保育経過記録（期ごと）ドラフトの必須欄・年齢分岐を検査する（空＝充足・§19）。

    日誌・月案と同じく「型としての成立」だけを決定的に検査する（表現の適否＝開示前提の
    肯定的・非断定的表現はレビューAI／指針整合＝eval の責務）。年齢分岐は日誌・月案と共通の
    _required_tag_type を使い、「発達の経過（development_notes）」の各叙述に
    0–2＝3つの視点 / 3–5＝5領域 のタグを課す（実務主流＝0歳:3つの視点/全年齢:5領域と一致・§19）。

    Args:
        record: 検査対象の保育経過記録ドラフト（ChildRecord）。

    Returns:
        違反メッセージのリスト。空リストなら "型" として成立。
    """
    problems: list[str] = []

    # ── 必須欄の充足（空文字も "未記入" 扱い） ── §19 保育経過記録：共通構造
    if not record.period.strip():
        problems.append("対象期間（period）が未記入")
    if not record.child_id.strip():
        problems.append("対象児（child_id）が未記入（保育経過記録は児童別＝§19）")
    if not record.overall_note.strip():
        problems.append("総合所見（overall_note）が未記入（期の育ちの総括＝§19）")
    if not record.development_notes:
        problems.append("発達の経過（development_notes）が空：年齢分岐タグ付きで1つ以上必要（§19）")

    # ── 年齢分岐：発達の経過に必須タグ体系を課す（0–2＝3つの視点 / 3–5＝5領域） ──
    required_tag_type, tag_label = _required_tag_type(record.age_band)
    for i, note in enumerate(record.development_notes):
        if not note.description.strip():
            problems.append(f"発達の経過[{i}]: 叙述（description）が未記入")
        if not any(isinstance(t, required_tag_type) for t in note.tags):
            problems.append(
                f"発達の経過[{i}]: {record.age_band.value} は{tag_label}のタグが1つ以上必要"
            )

    return problems


def validate_nursery_record_fields(record: NurseryRecord) -> list[str]:
    """保育要録（保育に関する記録）ドラフトの必須欄・年齢分岐を検査する（空＝充足・§19・L4）。

    日誌・月案・保育経過記録と同じく「型としての成立」だけを決定的に検査する（開示前提の肯定的・
    非断定的表現はレビューAI／指針整合＝eval の責務）。要録は年長（5歳児）専用のため年齢分岐は
    実質 5領域に畳まれるが、共通の _required_tag_type（三から五歳＝FiveDomains）を流用し
    「保育の展開と子どもの育ち（development_notes）」の各叙述にタグを課す（実装の二重化を避ける・§19）。

    Args:
        record: 検査対象の保育要録ドラフト（NurseryRecord）。

    Returns:
        違反メッセージのリスト。空リストなら "型" として成立。
    """
    problems: list[str] = []

    # ── 必須欄の充足（空文字も "未記入" 扱い） ── §19 保育要録：保育に関する記録
    if not record.fiscal_year.strip():
        problems.append("対象年度（fiscal_year）が未記入")
    if not record.child_id.strip():
        problems.append("対象児（child_id）が未記入（要録は児童別＝§19）")
    if not record.final_year_focus.strip():
        problems.append("最終年度の重点（final_year_focus）が未記入（§19）")
    if not record.individual_focus.strip():
        problems.append("個人の重点（individual_focus）が未記入（§19）")
    if not record.growth_until_final.strip():
        problems.append("最終年度に至るまでの育ち（growth_until_final）が未記入（§19）")
    if not record.development_notes:
        problems.append(
            "保育の展開と子どもの育ち（development_notes）が空：年齢分岐タグ付きで1つ以上必要（§19）"
        )

    # ── 年齢分岐：保育の展開に必須タグ体系を課す（年長＝5領域） ──
    required_tag_type, tag_label = _required_tag_type(record.age_band)
    for i, note in enumerate(record.development_notes):
        if not note.description.strip():
            problems.append(f"保育の展開と子どもの育ち[{i}]: 叙述（description）が未記入")
        if not any(isinstance(t, required_tag_type) for t in note.tags):
            problems.append(
                f"保育の展開と子どもの育ち[{i}]: {record.age_band.value} は{tag_label}のタグが1つ以上必要"
            )

    return problems
