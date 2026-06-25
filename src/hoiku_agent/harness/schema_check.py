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

from ..schemas import AgeBand, DiaryEntry, FiveDomains, MonthlyPlan, ThreeViewpoint


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
        problems.append("個別日誌（individual_notes）が空：0–2 個別は個の記録が本体（§3/§10）")
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
    if not plan.nurturing.strip():
        problems.append("養護（生命の保持・情緒の安定）が未記入（§10「養護／教育」）")
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
