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

from ..schemas import (
    ChildRecord,
    DevelopmentNote,
    DiaryEntry,
    IndividualNote,
    MonthlyEducationNote,
    MonthlyPlan,
    NurseryRecord,
)


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


def _format_note(note: IndividualNote, life_record_always: bool = True) -> str:
    # 個別の記録は児ごとに「姿＋枠組みタグ＋生活記録＋個人のねらい」をまとめて出す（標準様式）。
    # タグは枠組み（10の姿/3つの視点/5領域）を明示して出力する（§13）。
    # 生活記録は 0–2 で常時（養護の中核＝空欄も「―」で出す）、3–5 は記入があるときだけ添える
    # （3–5 標準様式に児別の生活記録欄は無い＝全年齢対応・§19）。
    tags = "、".join(t.value for t in note.tags) if note.tags else "（タグ未付与）"
    header = f"  ◆ {note.child_id}"
    if note.age_months.strip():
        header += f"（{note.age_months}）"
    lines = [
        header,
        f"    ・子どもの姿: {note.observed_state or '（未記入）'}",
        f"      └ 対応する姿/領域: {tags}",
    ]
    if life_record_always or not note.life_record.is_blank():
        lines.append(f"    ・生活記録: {_format_life_record(note)}")
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
    life_record_always = entry.age_band.value == "0-2"  # 0–2＝養護の中核として常時／3–5＝記入時のみ
    notes_block = (
        "\n".join(_format_note(n, life_record_always) for n in entry.individual_notes)
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


def _format_development(note: DevelopmentNote) -> str:
    # 発達の経過も枠組み（3つの視点/5領域/10の姿）を明示して出力する（§13/§19）。
    tags = "、".join(t.value for t in note.tags) if note.tags else "（タグ未付与）"
    return f"  - {note.description}\n    └ 対応する姿/領域: {tags}"


def write_child_record_draft(record: ChildRecord, template_ref: str | None = None) -> str:
    """児童票（期ごとの保育経過記録）ドラフトを標準様式テキストへ整形して返す（§19）。

    共通構造（越谷市公式様式・実務解説で裏取り）の順序：ヘッダ（期・対象児・月齢・年齢帯）→
    発達の経過（領域別叙述＋年齢分岐タグ明示）→ 配慮事項・特記 → 家庭との連携 → 総合所見 →
    次期に向けて。確認印欄は帳票PDF（web/chohyo_pdf）側で描く（テキスト版は本文のみ）。

    Args:
        record: 整形対象の児童票ドラフト。
        template_ref: 雛形のパス等（あれば様式に従う）。期制・欄名の園差で拡張可。

    Returns:
        様式に整形した文字列（枠組みタグを明示）。
    """
    development_block = (
        "\n".join(_format_development(n) for n in record.development_notes)
        if record.development_notes
        else "  （発達の経過 未記入）"
    )
    subject = record.child_id
    if record.age_months.strip():
        subject += f"（{record.age_months}）"
    lines = [
        f"■ 児童票・保育経過記録（{record.age_band.value} 歳児）　対象期間: {record.period}　対象児: {subject}",
        "",
        "【発達の経過（領域別の叙述）】",
        development_block,
        "",
        f"【配慮事項・特記】 {record.care_notes or '（なし）'}",
        "",
        f"【家庭との連携】 {record.family_liaison or '（なし）'}",
        "",
        "【総合所見】",
        f"  {record.overall_note}",
        "",
        f"【次期に向けて】 {record.next_aims or '（なし）'}",
    ]
    if template_ref:
        lines.append("")
        lines.append(f"（様式参照: {template_ref}）")
    return "\n".join(lines) + "\n"


def write_nursery_record_draft(record: NurseryRecord, template_ref: str | None = None) -> str:
    """保育要録（保育に関する記録）ドラフトを標準様式テキストへ整形して返す（§19・L4）。

    全国統一様式（こども家庭庁の参考例）の並び：ヘッダ（年度・対象児・年齢帯・就学先）→
    最終年度の重点 → 個人の重点 → 保育の展開と子どもの育ち（5領域＋10の姿タグ明示）→
    特に配慮すべき事項 → 最終年度に至るまでの育ち。児童票・月案（write_*_draft）と同じく
    枠組みタグ（5領域／10の姿）を明示出力する（§13）。3列レイアウトの帳票化・確認印欄は
    帳票PDF（web/chohyo_pdf）側で描く（テキスト版は本文のみ）。

    Args:
        record: 整形対象の保育要録ドラフト。
        template_ref: 雛形のパス等（あれば様式に従う）。園差で拡張可。

    Returns:
        様式に整形した文字列（枠組みタグを明示）。
    """
    development_block = (
        "\n".join(_format_development(n) for n in record.development_notes)
        if record.development_notes
        else "  （保育の展開と子どもの育ち 未記入）"
    )
    subject = record.child_id
    if record.age_months.strip():
        subject += f"（{record.age_months}）"
    header = f"■ 保育所児童保育要録（{record.age_band.value} 歳児）　対象年度: {record.fiscal_year}　対象児: {subject}"
    if record.school_name.strip():
        header += f"　就学先: {record.school_name}"
    lines = [
        header,
        "",
        "【最終年度の重点】",
        f"  {record.final_year_focus}",
        "",
        "【個人の重点】",
        f"  {record.individual_focus}",
        "",
        "【保育の展開と子どもの育ち（5領域・10の姿の視点）】",
        development_block,
        "",
        f"【特に配慮すべき事項】 {record.special_notes or 'なし'}",
        "",
        "【最終年度に至るまでの育ちに関する事項】",
        f"  {record.growth_until_final}",
    ]
    if template_ref:
        lines.append("")
        lines.append(f"（様式参照: {template_ref}）")
    return "\n".join(lines) + "\n"
