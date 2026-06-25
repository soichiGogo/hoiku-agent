"""harness：ドラフトの様式整形（決定的）。

設計コンテキスト §5/§6。write_draft の "実体" はここに1つだけ置く。tools/write_draft.py は
FunctionTool としてこれを呼ぶ薄いラッパ。確定出力（整形済みドラフト）の決定的実行は harness が
パイプライン末尾で行う（tool ではなくステップ＝§6・finalize.py）。

pydantic スキーマ（DiaryEntry 等）→ 園の様式テキストへ整形する。**10の姿/3つの視点/5領域の
タグを明示出力**する（§13 のドメイン作り込み＝差別化）。LLM は呼ばない。

実様式1枚はヒアリングで入手するまで未確定（§18）。template_ref が与えられればそれに寄せる
余地を残すが、v0 は越谷市様式の欄構成に倣った汎用様式で整形する（園差で拡張可＝末尾「など」）。
"""

from __future__ import annotations

from ..schemas import DiaryEntry, IndividualNote, MonthlyEducationNote, MonthlyPlan


def _format_attendance(entry: DiaryEntry) -> str:
    if not entry.attendance:
        return "（記録なし）"
    present = [a.child_id for a in entry.attendance if a.present]
    absent = [
        f"{a.child_id}（{a.reason or '理由未記入'}）" for a in entry.attendance if not a.present
    ]
    parts = [f"出席 {len(present)}名"]
    if absent:
        parts.append("欠席: " + "、".join(absent))
    return " / ".join(parts)


def _format_note(note: IndividualNote) -> str:
    # タグは枠組み（10の姿/3つの視点/5領域）を明示して出力する（§13）。
    tags = "、".join(t.value for t in note.tags) if note.tags else "（タグ未付与）"
    return f"  - [{note.child_id}] {note.observed_state}\n    └ 対応する姿/領域: {tags}"


def write_draft(entry: DiaryEntry, template_ref: str | None = None) -> str:
    """日誌ドラフト（DiaryEntry）を様式テキストへ整形して返す。

    Args:
        entry: 整形対象の日誌ドラフト。
        template_ref: 雛形のパス等（あれば様式に従う）。越谷市様式は末尾「など」＝園差で拡張可。

    Returns:
        様式に整形した文字列（10の姿/3つの視点/5領域タグを明示）。
    """
    notes_block = (
        "\n".join(_format_note(n) for n in entry.individual_notes)
        if entry.individual_notes
        else "  （個別記録なし）"
    )
    lines = [
        f"■ 保育日誌（{entry.age_band.value} 歳児クラス・個別）",
        f"日付: {entry.date}　天候: {entry.weather}",
        f"出欠: {_format_attendance(entry)}",
        f"健康状態: {entry.health_notes or '特記なし'}",
        "",
        "【保育の実践記録】",
        f"  {entry.practice_record}",
        "",
        "【個別の記録（子どもの姿）】",
        notes_block,
        "",
        "【評価・反省】",
        f"  (a) 子どもに焦点: {entry.evaluation.child_focus}",
        f"  (b) 自分の保育の適否: {entry.evaluation.self_review}",
        "",
        f"【保護者への連絡】 {entry.parent_contact or '（なし）'}",
    ]
    if template_ref:
        lines.append("")
        lines.append(f"（様式参照: {template_ref}）")
    return "\n".join(lines) + "\n"


def _format_education(note: MonthlyEducationNote) -> str:
    # 教育のねらいも枠組み（3つの視点/5領域/10の姿）を明示して出力する（§13）。
    tags = "、".join(t.value for t in note.tags) if note.tags else "（タグ未付与）"
    return f"  - {note.aim}\n    └ 対応する姿/領域: {tags}"


def write_monthly_draft(plan: MonthlyPlan, template_ref: str | None = None) -> str:
    """個別月案ドラフト（MonthlyPlan）を様式テキストへ整形して返す（§10）。

    日誌（write_draft）と同じく、養護／教育の枠組みタグ（0–2＝3つの視点 / 3–5＝5領域 / 10の姿）を
    明示出力する（§13 のドメイン作り込み＝差別化）。前月集積（L2 還流）由来の「前月の子どもの姿」も
    様式に明記する。実様式1枚は §18 未確定のため越谷市様式系の汎用様式に倣う（園差で拡張可）。

    Args:
        plan: 整形対象の月案ドラフト。
        template_ref: 雛形のパス等（あれば様式に従う）。

    Returns:
        様式に整形した文字列（養護／教育・枠組みタグを明示）。
    """
    education_block = (
        "\n".join(_format_education(n) for n in plan.education)
        if plan.education
        else "  （教育のねらい未記入）"
    )
    lines = [
        f"■ 月案（個別・{plan.age_band.value} 歳児）　対象月: {plan.month}　対象児: {plan.child_id}",
        "",
        "【前月の子どもの姿】",
        f"  {plan.prev_child_state}",
        "",
        "【今月のねらい・内容】",
        f"  {plan.monthly_goals}",
        "",
        "【養護】",
        f"  {plan.nurturing}",
        "",
        "【教育（ねらい・内容）】",
        education_block,
        "",
        "【環境構成・援助（配慮）】",
        f"  {plan.environment_support}",
        "",
        f"【行事／家庭連携／食育・健康】 {plan.events_family_food or '（なし）'}",
        "",
        "【評価・反省】",
        f"  {plan.evaluation_reflection}",
    ]
    if template_ref:
        lines.append("")
        lines.append(f"（様式参照: {template_ref}）")
    return "\n".join(lines) + "\n"
