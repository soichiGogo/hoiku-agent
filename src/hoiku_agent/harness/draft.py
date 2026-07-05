"""harness：ドラフトの様式整形（決定的・テンプレ駆動）。

設計コンテキスト §5/§6/§18。write_draft の "実体" はここに1つだけ置く。tools/write_draft.py は
FunctionTool としてこれを呼ぶ薄いラッパ。確定出力（整形済みドラフト）の決定的実行は harness が
パイプライン末尾で行う（tool ではなくステップ＝§6・finalize.py）。

**本文レイアウト（章立て＝セクションの順序・見出しラベル・種別・任意欄の出し分け）は
`knowledge/様式テンプレート.json`（`harness/template_store`）にデータとして持ち、ここはそれを歩いて
描く**（レイアウトの二重管理を解消し、特定園の様式差＝§18 をコード改修でなくテンプレ編集で吸収する）。
ヘッダの合成（タイトル・対象児/期間等）と、個別記録ブロック・生活記録・出欠サマリなどの**構造的な
描画はコード**に残す（テンプレは式言語を作らず、閉じた語彙に留める＝§5 の線をテンプレに漏らさない）。

pydantic スキーマ（DiaryEntry 等）→ 園の様式テキストへ整形する。**10の姿/3つの視点/5領域の
タグを明示出力**する（§13 のドメイン作り込み＝差別化）。LLM は呼ばない。

様式はネット調査（公的＝川口市・越谷市の参考様式、厚労省/こども家庭庁の告示、保育専門メディア）で
裏取りした標準様式に倣う（§18。日誌＝基本情報→本日のねらい→出欠→主な活動→個別の記録→健康・視診→
家庭連絡→評価反省、月案＝前月の姿→今月のねらい→養護（2本柱）→教育→環境・援助→家庭連携→評価反省、
保育経過記録＝発達の経過→配慮特記→家庭連携→総合所見→次期、要録＝最終年度の重点→個人の重点→保育の展開→
特に配慮すべき事項→最終年度に至るまでの育ち）。この順序・ラベルはテンプレ側が持つ。
template_ref が与えられればそれに寄せる余地を残す。
"""

from __future__ import annotations

from ..schemas import (
    ChildRecord,
    DiaryEntry,
    IndividualNote,
    MonthlyPlan,
    NurseryRecord,
)
from ..schemas.template import DocTemplate, Section, SectionKind
from .template_store import load_template


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


def _format_tagged_item(note, item_field: str) -> str:
    # 枠組みタグ付きの叙述1件（月案の教育＝aim／保育経過記録・要録の発達の経過＝description）を明示タグ付きで出す。
    # 枠組み（3つの視点/5領域/10の姿）を明示して出力する（§13）。月案/保育経過記録/要録で共用（旧
    # _format_education/_format_development を統合＝二重実装しない）。
    text = getattr(note, item_field)
    tags = "、".join(t.value for t in note.tags) if note.tags else "（タグ未付与）"
    return f"  - {text}\n    └ 対応する姿/領域: {tags}"


# ──────────────────────────── 本文レンダラ（テンプレ駆動・§18） ────────────────────────────


def _field_value(model, key: str):
    return getattr(model, key, None)


def _should_show(section: Section, model) -> bool:
    """セクションの出し分け（常時／対象フィールドが非空のときだけ）。"""
    if section.show.value == "always":
        return True
    val = _field_value(model, section.key)
    if isinstance(val, str):
        return bool(val.strip())
    if isinstance(val, list):
        return bool(val)
    return val is not None


def _render_section(section: Section, model) -> list[str]:
    """1セクションを行のリストに描く（種別＝コード側レンダラを選ぶ。テンプレは順序/ラベル/種別を持つ）。"""
    kind = section.kind
    label = section.label
    if kind is SectionKind.text_block:
        v = _field_value(model, section.key) or ""
        return [f"【{label}】", f"  {str(v) or section.blank}"]
    if kind is SectionKind.text_inline:
        v = _field_value(model, section.key) or ""
        return [f"【{label}】 {str(v) or section.blank}"]
    if kind is SectionKind.attendance:
        return [f"【{label}】 {_format_attendance(model)}"]
    if kind is SectionKind.individual_notes:
        notes = _field_value(model, section.key) or []
        life_always = model.age_band.value == "0-2"
        block = (
            "\n".join(_format_note(n, life_always) for n in notes)
            if notes
            else f"  {section.blank}"
        )
        return [f"【{label}】", block]
    if kind is SectionKind.tagged_list:
        items = _field_value(model, section.key) or []
        block = (
            "\n".join(_format_tagged_item(it, section.item_field) for it in items)
            if items
            else f"  {section.blank}"
        )
        return [f"【{label}】", block]
    if kind is SectionKind.evaluation2:
        ev = _field_value(model, section.key)
        return [
            f"【{label}】",
            f"  (a) 子どもに焦点: {ev.child_focus}",
            f"  (b) 自分の保育の適否（ねらい・環境構成・関わり）: {ev.self_review}",
        ]
    raise ValueError(f"未知のセクション種別: {kind!r}")  # スキーマで閉じているので通常来ない


def _render_body(template: DocTemplate, model) -> list[str]:
    """テンプレの本文セクションを順に描き、セクション間に空行を1つ挟んだ行リストを返す。

    ヘッダ（タイトル行）に続けて write_* が並べるため、各セクションの前に "" を1つ入れる
    （ヘッダ→空行→セクション→空行→…＝標準様式の見た目）。
    """
    lines: list[str] = []
    for section in template.sections:
        if not _should_show(section, model):
            continue
        lines.append("")
        lines.extend(_render_section(section, model))
    return lines


def _with_template_ref(lines: list[str], template_ref: str | None) -> str:
    if template_ref:
        lines = [*lines, "", f"（様式参照: {template_ref}）"]
    return "\n".join(lines) + "\n"


def write_draft(entry: DiaryEntry, template_ref: str | None = None) -> str:
    """日誌ドラフト（DiaryEntry）を標準様式テキストへ整形して返す（本文レイアウトはテンプレ駆動）。

    Args:
        entry: 整形対象の日誌ドラフト。
        template_ref: 雛形のパス等（あれば様式に従う）。園差で拡張可。

    Returns:
        様式に整形した文字列（標準様式の章立て・順序＝テンプレ。10の姿/3つの視点/5領域タグを明示）。
    """
    # ヘッダ（記録日・天候は常時／気温・組は標準様式の任意欄＝記入時のみ添える・§10）。
    header_meta = f"記録日: {entry.date}　天候: {entry.weather or '（未記入）'}"
    if entry.temperature.strip():
        header_meta += f"　気温: {entry.temperature}"
    if entry.class_name.strip():
        header_meta += f"　組: {entry.class_name}"
    lines = [
        f"■ 保育日誌（{entry.age_band.value} 歳児クラス・個別）",
        header_meta,
        *_render_body(load_template("diary"), entry),
    ]
    return _with_template_ref(lines, template_ref)


def write_monthly_draft(plan: MonthlyPlan, template_ref: str | None = None) -> str:
    """個別月案ドラフト（MonthlyPlan）を標準様式テキストへ整形して返す（§10・本文はテンプレ駆動）。

    制度準拠の順序（前月の姿→今月のねらい→養護（生命の保持／情緒の安定）→教育→環境・援助→家庭連携→
    評価・反省）はテンプレ側が持つ（養護を教育より前に置くのが指針整合＝標準様式調査）。養護／教育の
    枠組みタグ（0–2＝3つの視点 / 3–5＝5領域 / 10の姿）は tagged_list/text 描画で明示する（§13）。
    """
    subject = plan.child_id
    if plan.age_months.strip():
        subject += f"（{plan.age_months}）"
    lines = [
        f"■ 月案（個別・{plan.age_band.value} 歳児）　対象月: {plan.month}　対象児: {subject}",
        *_render_body(load_template("monthly"), plan),
    ]
    return _with_template_ref(lines, template_ref)


def write_child_record_draft(record: ChildRecord, template_ref: str | None = None) -> str:
    """保育経過記録（期ごと）ドラフトを標準様式テキストへ整形して返す（§19・本文はテンプレ駆動）。

    共通構造（越谷市公式様式・実務解説で裏取り）の順序（ヘッダ→発達の経過→配慮・特記→家庭連携→
    総合所見→次期）はテンプレ側が持つ。確認印欄は帳票PDF（web/chohyo_pdf）側で描く（テキスト版は本文のみ）。
    """
    subject = record.child_id
    if record.age_months.strip():
        subject += f"（{record.age_months}）"
    lines = [
        f"■ 保育経過記録（{record.age_band.value} 歳児）"
        f"　対象期間: {record.period}　対象児: {subject}",
        *_render_body(load_template("child_record"), record),
    ]
    return _with_template_ref(lines, template_ref)


def write_nursery_record_draft(record: NurseryRecord, template_ref: str | None = None) -> str:
    """保育要録（保育に関する記録）ドラフトを標準様式テキストへ整形して返す（§19・L4・本文はテンプレ駆動）。

    全国統一様式（こども家庭庁の参考例）の並び（ヘッダ→最終年度の重点→個人の重点→保育の展開と
    子どもの育ち→特に配慮すべき事項→最終年度に至るまでの育ち）はテンプレ側が持つ。枠組みタグ
    （5領域／10の姿）は tagged_list 描画で明示する（§13）。3列レイアウト・確認印欄は帳票PDF 側で描く。
    """
    subject = record.child_id
    if record.age_months.strip():
        subject += f"（{record.age_months}）"
    title = (
        f"■ 保育所児童保育要録（{record.age_band.value} 歳児）"
        f"　対象年度: {record.fiscal_year}　対象児: {subject}"
    )
    if record.school_name.strip():
        title += f"　就学先: {record.school_name}"
    lines = [title, *_render_body(load_template("nursery_record"), record)]
    return _with_template_ref(lines, template_ref)
