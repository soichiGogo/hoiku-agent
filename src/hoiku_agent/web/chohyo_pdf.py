"""確定書類（final_entry）→ 園の様式に近い「帳票PDF」への描画（層A/web の presentation）。

設計コンテキスト §11（配信UI）／ §18（“園の様式で出す”最終形）。ここは **描画だけ** で、必須欄・年齢分岐等の
決定的ロジック（型の保証）は harness が持つ（§5）。欄順は harness の `write_draft`/`write_monthly_draft`
（ネット調査で裏取りした 0–2 個別の標準様式）と同じにそろえる（テキスト版と帳票版で様式順を一致させる。
validation/判断は持たない＝二重定義ではない）。

PDF は ReportLab で生成する：純 pip・**システムライブラリ不要**（apt/Cairo/Pango 不要＝Dockerfile 不変）。
日本語は **IPAex ゴシックを埋め込む**（`web/fonts/ipaexg.ttf`・再配布可＝IPA Font License v1.0）。組み込み CID
フォント（Heisei）だと閲覧側に CJK フォントが無いと**グリフが空白化**するため、公式書類として確実に表示・印刷
できるよう TTF を埋め込む（reportlab は既定でサブセット埋め込み＝PDF は小さい）。ユーザー入力は Paragraph の
マークアップ解釈を避けるため必ず XML エスケープする。
"""

from __future__ import annotations

import io
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

# 日本語フォント（IPAex ゴシックを埋め込む）。モジュールロード時に1回だけ登録する。
# 実行は source から（uvicorn server:app）＝モジュール相対で解決。Docker も COPY src で同梱される。
_FONT = "IPAexGothic"
_FONT_PATH = Path(__file__).resolve().parent / "fonts" / "ipaexg.ttf"
pdfmetrics.registerFont(TTFont(_FONT, str(_FONT_PATH)))

_AGE_LABEL = {"0-2": "0〜2歳児", "3-5": "3〜5歳児"}

# レイアウト定数（A4・左右 15mm 余白＝本文幅 180mm）。
_MARGIN = 15 * mm
_CONTENT_W = A4[0] - 2 * _MARGIN
_LABEL_W = 30 * mm  # セクションのラベル列

_TITLE = ParagraphStyle("title", fontName=_FONT, fontSize=14, leading=18)
_META = ParagraphStyle(
    "meta", fontName=_FONT, fontSize=9, leading=12, textColor=colors.HexColor("#444444")
)
_LABEL = ParagraphStyle("label", fontName=_FONT, fontSize=9.5, leading=13)
_BODY = ParagraphStyle("body", fontName=_FONT, fontSize=10, leading=14)
_SMALL = ParagraphStyle("small", fontName=_FONT, fontSize=9, leading=12.5)
_CHILD = ParagraphStyle("child", fontName=_FONT, fontSize=10.5, leading=14)

_HEADER_BG = colors.HexColor("#efe9dd")  # ラベル/見出しセルの淡い地
_LINE = colors.HexColor("#8a8378")


def _t(value: object) -> str:
    """None/空を安全な文字列にし、Paragraph 用に XML エスケープする。"""
    if value is None:
        return ""
    return escape(str(value))


def _P(value: object, style: ParagraphStyle = _BODY) -> Paragraph:
    text = _t(value)
    return Paragraph(text if text else "&nbsp;", style)


def _section(label: str, content) -> Table:
    """ラベル列＋内容列の1セクション行（帳票の基本ブロック）。content は Paragraph か flowable のリスト。"""
    tbl = Table(
        [[_P(label, _LABEL), content]],
        colWidths=[_LABEL_W, _CONTENT_W - _LABEL_W],
    )
    tbl.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.6, _LINE),
                ("BACKGROUND", (0, 0), (0, 0), _HEADER_BG),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    return tbl


def _life_record_table(lr: dict) -> Table:
    """0–2 養護の中核＝生活記録（食事/睡眠/排泄/機嫌・体調）を4列の小表で描く。

    幅は本文全幅（_CONTENT_W）を4等分し、他のセクション行と左端・右端をそろえる。ReportLab の Table は
    既定で hAlign="CENTER"（中央寄せ）なので、幅が本文未満だと帳票の罫線がズレて見える。全幅＋LEFT で固定する。
    """
    lr = lr or {}
    w = _CONTENT_W / 4
    tbl = Table(
        [
            [
                _P("食事", _LABEL),
                _P("睡眠", _LABEL),
                _P("排泄", _LABEL),
                _P("機嫌・体調・視診", _LABEL),
            ],
            [
                _P(lr.get("meal"), _SMALL),
                _P(lr.get("sleep"), _SMALL),
                _P(lr.get("toilet"), _SMALL),
                _P(lr.get("mood_health"), _SMALL),
            ],
        ],
        colWidths=[w, w, w, w],
    )
    tbl.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.6, _LINE),
                ("BACKGROUND", (0, 0), (-1, 0), _HEADER_BG),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    tbl.hAlign = "LEFT"
    return tbl


def _child_block(note: dict, life_record_always: bool = True) -> KeepTogether:
    """個別の記録1件（児ごと）。ページ跨ぎを避けてまとめて出す。

    生活記録の4列表は 0–2 で常時（養護の中核）、3–5 は記入があるときだけ描く
    （3–5 標準様式に児別の生活記録欄は無い＝全年齢対応・§19。harness の write_draft と同順）。
    """
    note = note or {}
    months = str(note.get("age_months") or "").strip()
    head = note.get("child_id") or "（対象児）"
    if months:
        head = f"{head}（{months}）"
    tags = note.get("tags") or []
    tag_text = "、".join(str(t) for t in tags) if tags else "（タグ未付与）"
    inner = Table(
        [
            [_P("子どもの姿", _LABEL), _P(note.get("observed_state"), _SMALL)],
            [_P("対応する姿・領域", _LABEL), _P(tag_text, _SMALL)],
        ],
        colWidths=[_LABEL_W, _CONTENT_W - _LABEL_W],
    )
    inner.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.6, _LINE),
                ("BACKGROUND", (0, 0), (0, -1), _HEADER_BG),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    parts = [
        _P(f"◆ {_t(head)}", _CHILD),
        Spacer(1, 1.5 * mm),
        inner,
    ]
    lr = note.get("life_record") or {}
    if life_record_always or any(str(lr.get(k) or "").strip() for k in lr):
        parts.append(_life_record_table(lr))
    aim = str(note.get("individual_aim") or "").strip()
    if aim:
        parts.append(_section("個人のねらい", _P(aim, _SMALL)))
    parts.append(Spacer(1, 3 * mm))
    return KeepTogether(parts)


def _development_block(note: dict) -> KeepTogether:
    """児童票「発達の経過」1件（叙述＋対応する姿・領域）。ページ跨ぎを避けてまとめて出す。"""
    note = note or {}
    tags = note.get("tags") or []
    tag_text = "、".join(str(t) for t in tags) if tags else "（タグ未付与）"
    inner = Table(
        [
            [_P("経過（叙述）", _LABEL), _P(note.get("description"), _SMALL)],
            [_P("対応する姿・領域", _LABEL), _P(tag_text, _SMALL)],
        ],
        colWidths=[_LABEL_W, _CONTENT_W - _LABEL_W],
    )
    inner.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.6, _LINE),
                ("BACKGROUND", (0, 0), (0, -1), _HEADER_BG),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    return KeepTogether([inner, Spacer(1, 2 * mm)])


def _attendance_text(attendance: list) -> str:
    present = [a for a in (attendance or []) if a and a.get("present")]
    absent = [a for a in (attendance or []) if a and not a.get("present")]
    parts = [f"出席 {len(present)}名"]
    if absent:
        parts.append(
            "欠席: "
            + "、".join(
                f"{a.get('child_id', '')}（{a.get('reason') or '理由未記入'}）" for a in absent
            )
        )
    return " ／ ".join(parts)


def _signoff_block() -> KeepTogether:
    """確認印欄（担任／主任／園長）。公式記録として押印・確認のための空欄を設ける（描画のみ・型検査なし）。

    日誌/月案の末尾に共通で置く。3列＝担任/主任/園長、下段は押印・署名用の余白セル。園差で欄名は変わりうるが、
    標準様式（自治体様式）で確認印3欄が一般的なためこれを既定にする（現場の実様式が来たら欄名を寄せる＝§18）。
    """
    w = _CONTENT_W / 3
    tbl = Table(
        [
            [_P("担任", _LABEL), _P("主任", _LABEL), _P("園長", _LABEL)],
            ["", "", ""],
        ],
        colWidths=[w, w, w],
        rowHeights=[None, 16 * mm],
    )
    tbl.hAlign = "LEFT"
    tbl.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.6, _LINE),
                ("BACKGROUND", (0, 0), (-1, 0), _HEADER_BG),
                ("ALIGN", (0, 0), (-1, 0), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    return KeepTogether([Spacer(1, 4 * mm), _P("確認", _LABEL), Spacer(1, 1.5 * mm), tbl])


def _diary_story(entry: dict) -> list:
    age = entry.get("age_band") or "0-2"
    # ヘッダのメタ（記録日・天候は常時／気温・組は記入時のみ添える）。_P が全体を1回だけ XML エスケープするため、
    # ここでは生値を渡す（f-string 内で _t すると二重エスケープになる）。
    meta_bits = [
        f"記録日: {entry.get('date') or ''}",
        f"天候: {entry.get('weather') or ''}",
    ]
    temperature = str(entry.get("temperature") or "").strip()
    if temperature:
        meta_bits.append(f"気温: {temperature}")
    meta_bits.append(f"クラス: {_AGE_LABEL.get(age, age)}")
    class_name = str(entry.get("class_name") or "").strip()
    if class_name:
        meta_bits.append(f"組: {class_name}")
    story: list = [
        _P(f"保育日誌（{_AGE_LABEL.get(age, age)}・個別）", _TITLE),
        _P("　　".join(meta_bits), _META),
        Spacer(1, 3 * mm),
        _section("本日のねらい", _P(entry.get("daily_aim"))),
        _section("出欠", _P(_attendance_text(entry.get("attendance")))),
        _section("主な活動・保育者の援助", _P(entry.get("practice_record"))),
        Spacer(1, 2 * mm),
        _P("個別の記録（子ども一人ひとりの姿・生活）", _LABEL),
        Spacer(1, 1.5 * mm),
    ]
    notes = entry.get("individual_notes") or []
    life_record_always = age == "0-2"  # 0–2＝養護の中核として常時／3–5＝記入時のみ（§19）
    if notes:
        story.extend(_child_block(n, life_record_always) for n in notes)
    else:
        story.append(_section("", _P("（個別記録なし）")))
    story.extend(
        [
            _section("健康・視診", _P(entry.get("health_notes") or "特記なし")),
            _section("家庭への連絡", _P(entry.get("parent_contact") or "（なし）")),
        ]
    )
    ev = entry.get("evaluation") or {}
    story.append(_section("評価・反省 (a) 子どもに焦点", _P(ev.get("child_focus"))))
    story.append(_section("評価・反省 (b) 自分の保育の適否", _P(ev.get("self_review"))))
    story.append(_signoff_block())
    return story


def _monthly_story(entry: dict) -> list:
    age = entry.get("age_band") or "0-2"
    subject = entry.get("child_id") or "（対象児）"
    months = str(entry.get("age_months") or "").strip()
    if months:
        subject = f"{subject}（{months}）"
    story: list = [
        _P(f"月案（個別・{_AGE_LABEL.get(age, age)}）", _TITLE),
        # _P が1回だけエスケープするため生値を渡す（f-string 内 _t は二重エスケープになる）。
        _P(f"対象月: {entry.get('month') or ''}　　対象児: {subject}", _META),
        Spacer(1, 3 * mm),
        _section("前月の子どもの姿", _P(entry.get("prev_child_state"))),
        _section("今月のねらい・内容", _P(entry.get("monthly_goals"))),
        _section("養護：生命の保持", _P(entry.get("nurturing_life"))),
        _section("養護：情緒の安定", _P(entry.get("nurturing_emotion"))),
        Spacer(1, 2 * mm),
        _P("教育（ねらい・内容）", _LABEL),
        Spacer(1, 1.5 * mm),
    ]
    edu = entry.get("education") or []
    if edu:
        for note in edu:
            note = note or {}
            tags = note.get("tags") or []
            tag_text = "、".join(str(t) for t in tags) if tags else "（タグ未付与）"
            story.append(_section("ねらい・内容", _P(note.get("aim"), _SMALL)))
            story.append(_section("対応する姿・領域", _P(tag_text, _SMALL)))
            story.append(Spacer(1, 2 * mm))
    else:
        story.append(_section("", _P("（教育のねらい未記入）")))
    story.extend(
        [
            _section("環境構成・援助（配慮）", _P(entry.get("environment_support"))),
            _section(
                "家庭との連携／食育・健康・行事", _P(entry.get("events_family_food") or "（なし）")
            ),
            _section("評価・反省", _P(entry.get("evaluation_reflection"))),
        ]
    )
    story.append(_signoff_block())
    return story


def _child_record_story(entry: dict) -> list:
    """児童票（期ごとの保育経過記録）。欄順は harness の write_child_record_draft（標準様式）と一致させる。"""
    age = entry.get("age_band") or "0-2"
    subject = entry.get("child_id") or "（対象児）"
    months = str(entry.get("age_months") or "").strip()
    if months:
        subject = f"{subject}（{months}）"
    story: list = [
        _P(f"児童票・保育経過記録（{_AGE_LABEL.get(age, age)}）", _TITLE),
        # _P が1回だけエスケープするため生値を渡す（f-string 内 _t は二重エスケープになる）。
        _P(f"対象期間: {entry.get('period') or ''}　　対象児: {subject}", _META),
        Spacer(1, 3 * mm),
        _P("発達の経過（領域別の叙述）", _LABEL),
        Spacer(1, 1.5 * mm),
    ]
    notes = entry.get("development_notes") or []
    if notes:
        story.extend(_development_block(n) for n in notes)
    else:
        story.append(_section("", _P("（発達の経過 未記入）")))
    story.extend(
        [
            _section("配慮事項・特記", _P(entry.get("care_notes") or "（なし）")),
            _section("家庭との連携", _P(entry.get("family_liaison") or "（なし）")),
            _section("総合所見", _P(entry.get("overall_note"))),
            _section("次期に向けて", _P(entry.get("next_aims") or "（なし）")),
        ]
    )
    story.append(_signoff_block())
    return story


_BUILDERS = {"diary": _diary_story, "monthly": _monthly_story, "child_record": _child_record_story}


def render_pdf(kind: str, entry: dict) -> bytes:
    """確定 entry（dict）を帳票PDF（bytes）へ描画する。kind = "diary" | "monthly" | "child_record"。

    描画のみ（型検査はしない＝空欄は空セルで出す）。entry が dict でない・kind 不正は ValueError。
    """
    if kind not in _BUILDERS:
        raise ValueError(f"未知の kind: {kind!r}（'diary' | 'monthly' | 'child_record'）")
    if not isinstance(entry, dict):
        raise ValueError("entry は dict である必要があります")
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=_MARGIN,
        rightMargin=_MARGIN,
        topMargin=_MARGIN,
        bottomMargin=_MARGIN,
        title={"diary": "保育日誌", "monthly": "個別月案", "child_record": "児童票"}[kind],
    )
    doc.build(_BUILDERS[kind](entry))
    return buf.getvalue()
