"""harness：ドラフトの様式整形（決定的）。

設計コンテキスト §5/§6。write_draft の "実体" はここに1つだけ置く。tools/write_draft.py は
FunctionTool としてこれを呼ぶ薄いラッパ。確定出力（整形済みドラフト）の決定的実行は harness が
パイプライン末尾で行う（tool ではなくステップ＝§6・finalize.py）。

pydantic スキーマ（DiaryEntry 等）→ 園の様式テキストへ整形する。**10の姿/3つの視点/5領域の
タグを明示出力**する（§13 のドメイン作り込み＝差別化）。LLM は呼ばない。

様式はネット調査（公的＝川口市・越谷市の参考様式、厚労省/こども家庭庁の告示、保育専門メディア）で
裏取りした **0–2 個別の標準様式** に倣う（§18）。日誌は「基本情報→本日のねらい→出欠→主な活動→
個別の記録（姿＋生活記録）→健康・視診→家庭連絡→評価・反省」、月案は制度準拠の「前月の姿→今月の
ねらい→**養護（生命の保持／情緒の安定の2本柱）→教育**→環境・援助→家庭連携→評価・反省」の順
（養護を教育より前に置くのが指針整合）。実様式1枚での確定までは欄差を「など」で許容し拡張可に保つ。
template_ref が与えられればそれに寄せる余地を残す。
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


def _format_life_record(note: IndividualNote) -> str:
    """0–2 養護の中核＝個別の生活記録（食事・睡眠・排泄・機嫌/体調）を1行に整形する。"""
    lr = note.life_record
    return "／".join(
        [
            f"食事 {lr.meal or '―'}",
            f"睡眠 {lr.sleep or '―'}",
            f"排泄 {lr.toilet or '―'}",
            f"機嫌・体調 {lr.mood_health or '―'}",
        ]
    )


def _format_note(note: IndividualNote) -> str:
    # 0–2 個別の記録は児ごとに「姿＋枠組みタグ＋生活記録＋個人のねらい」をまとめて出す（標準様式）。
    # タグは枠組み（10の姿/3つの視点/5領域）を明示して出力する（§13）。
    tags = "、".join(t.value for t in note.tags) if note.tags else "（タグ未付与）"
    header = f"  ◆ {note.child_id}"
    if note.age_months.strip():
        header += f"（{note.age_months}）"
    lines = [
        header,
        f"    ・子どもの姿: {note.observed_state or '（未記入）'}",
        f"      └ 対応する姿/領域: {tags}",
        f"    ・生活記録: {_format_life_record(note)}",
    ]
    if note.individual_aim.strip():
        lines.append(f"    ・個人のねらい: {note.individual_aim}")
    return "\n".join(lines)


def write_draft(entry: DiaryEntry, template_ref: str | None = None) -> str:
    """日誌ドラフト（DiaryEntry）を標準様式テキストへ整形して返す。

    Args:
        entry: 整形対象の日誌ドラフト。
        template_ref: 雛形のパス等（あれば様式に従う）。園差で拡張可。

    Returns:
        様式に整形した文字列（標準様式の章立て・順序。10の姿/3つの視点/5領域タグを明示）。
    """
    notes_block = (
        "\n".join(_format_note(n) for n in entry.individual_notes)
        if entry.individual_notes
        else "  （個別記録なし）"
    )
    # ヘッダ（記録日・天候は常時／気温・組は標準様式の任意欄＝記入時のみ添える・§10）
    header_meta = f"記録日: {entry.date}　天候: {entry.weather or '（未記入）'}"
    if entry.temperature.strip():
        header_meta += f"　気温: {entry.temperature}"
    if entry.class_name.strip():
        header_meta += f"　組: {entry.class_name}"
    lines = [
        f"■ 保育日誌（{entry.age_band.value} 歳児クラス・個別）",
        header_meta,
        "",
        "【本日のねらい（養護・教育）】",
        f"  {entry.daily_aim or '（未記入）'}",
        "",
        f"【出欠】 {_format_attendance(entry)}",
        "",
        "【主な活動・保育者の援助】",
        f"  {entry.practice_record}",
        "",
        "【個別の記録（子ども一人ひとりの姿・生活）】",
        notes_block,
        "",
        f"【健康・視診】 {entry.health_notes or '特記なし'}",
        "",
        f"【家庭への連絡】 {entry.parent_contact or '（なし）'}",
        "",
        "【評価・反省】",
        f"  (a) 子どもに焦点: {entry.evaluation.child_focus}",
        f"  (b) 自分の保育の適否（ねらい・環境構成・関わり）: {entry.evaluation.self_review}",
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
    """個別月案ドラフト（MonthlyPlan）を標準様式テキストへ整形して返す（§10）。

    制度準拠の順序（前月の姿→今月のねらい→**養護（生命の保持／情緒の安定）→教育**→環境・援助→
    家庭連携→評価・反省）で並べる（養護を教育より前に置くのが指針整合＝標準様式調査）。日誌（write_draft）
    と同じく養護／教育の枠組みタグ（0–2＝3つの視点 / 3–5＝5領域 / 10の姿）を明示出力する（§13）。

    Args:
        plan: 整形対象の月案ドラフト。
        template_ref: 雛形のパス等（あれば様式に従う）。

    Returns:
        様式に整形した文字列（養護2本柱／教育・枠組みタグを明示）。
    """
    education_block = (
        "\n".join(_format_education(n) for n in plan.education)
        if plan.education
        else "  （教育のねらい未記入）"
    )
    subject = plan.child_id
    if plan.age_months.strip():
        subject += f"（{plan.age_months}）"
    lines = [
        f"■ 月案（個別・{plan.age_band.value} 歳児）　対象月: {plan.month}　対象児: {subject}",
        "",
        "【前月の子どもの姿】",
        f"  {plan.prev_child_state}",
        "",
        "【今月のねらい・内容】",
        f"  {plan.monthly_goals}",
        "",
        "【養護：生命の保持】",
        f"  {plan.nurturing_life}",
        "",
        "【養護：情緒の安定】",
        f"  {plan.nurturing_emotion}",
        "",
        "【教育（ねらい・内容）】",
        education_block,
        "",
        "【環境構成・援助（配慮）】",
        f"  {plan.environment_support}",
        "",
        f"【家庭との連携／食育・健康・行事】 {plan.events_family_food or '（なし）'}",
        "",
        "【評価・反省】",
        f"  {plan.evaluation_reflection}",
    ]
    if template_ref:
        lines.append("")
        lines.append(f"（様式参照: {template_ref}）")
    return "\n".join(lines) + "\n"
