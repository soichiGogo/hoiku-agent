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
    """0–2 養護の中核＝生活記録（食事/睡眠/排泄/機嫌・体調）を4列の小表で描く。"""
    lr = lr or {}
    w = (_CONTENT_W - _LABEL_W) / 4
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
    return tbl


def _child_block(note: dict) -> KeepTogether:
    """個別の記録1件（児ごと）。ページ跨ぎを避けてまとめて出す。"""
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
        _life_record_table(note.get("life_record") or {}),
    ]
    aim = str(note.get("individual_aim") or "").strip()
    if aim:
        parts.append(_section("個人のねらい", _P(aim, _SMALL)))
    parts.append(Spacer(1, 3 * mm))
    return KeepTogether(parts)


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


def _diary_story(entry: dict) -> list:
    age = entry.get("age_band") or "0-2"
    story: list = [
        _P(f"保育日誌（{_AGE_LABEL.get(age, age)}・個別）", _TITLE),
        _P(
            f"記録日: {_t(entry.get('date'))}　　天候: {_t(entry.get('weather'))}　　クラス: {_AGE_LABEL.get(age, age)}",
            _META,
        ),
        Spacer(1, 3 * mm),
        _section("本日のねらい", _P(entry.get("daily_aim"))),
        _section("出欠", _P(_attendance_text(entry.get("attendance")))),
        _section("主な活動・保育者の援助", _P(entry.get("practice_record"))),
        Spacer(1, 2 * mm),
        _P("個別の記録（子ども一人ひとりの姿・生活）", _LABEL),
        Spacer(1, 1.5 * mm),
    ]
    notes = entry.get("individual_notes") or []
    if notes:
        story.extend(_child_block(n) for n in notes)
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
    return story


def _monthly_story(entry: dict) -> list:
    age = entry.get("age_band") or "0-2"
    subject = entry.get("child_id") or "（対象児）"
    months = str(entry.get("age_months") or "").strip()
    if months:
        subject = f"{subject}（{months}）"
    story: list = [
        _P(f"月案（個別・{_AGE_LABEL.get(age, age)}）", _TITLE),
        _P(f"対象月: {_t(entry.get('month'))}　　対象児: {_t(subject)}", _META),
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
    return story


_BUILDERS = {"diary": _diary_story, "monthly": _monthly_story}


def render_pdf(kind: str, entry: dict) -> bytes:
    """確定 entry（dict）を帳票PDF（bytes）へ描画する。kind = "diary" | "monthly"。

    描画のみ（型検査はしない＝空欄は空セルで出す）。entry が dict でない・kind 不正は ValueError。
    """
    if kind not in _BUILDERS:
        raise ValueError(f"未知の kind: {kind!r}（'diary' | 'monthly'）")
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
        title="保育日誌" if kind == "diary" else "個別月案",
    )
    doc.build(_BUILDERS[kind](entry))
    return buf.getvalue()
