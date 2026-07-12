"""確定書類（final_entry）→ 園の様式に近い「帳票PDF」への描画（層A/web の presentation）。

設計コンテキスト §11（配信UI）／ §18（“園の様式で出す”最終形）。ここは **描画だけ** で、必須欄・年齢分岐等の
決定的ロジック（型の保証）は harness が持つ（§5）。日誌/月案の欄順は harness の `write_draft`/
`write_monthly_draft`（ネット調査で裏取りした標準様式）と同じにそろえる（テキスト版と帳票版で様式順を一致させる。
validation/判断は持たない＝二重定義ではない）。**保育経過記録は年間マトリクス様式（実様式準拠・§19）**＝A4 横・
行＝領域×列＝4期の年間1枚（テキスト版は期の縦型＝コピー用で役割分担）。

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
from reportlab.lib.pagesizes import A4, landscape
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
from reportlab.platypus.doctemplate import LayoutError

from ..harness.child_record_period import parse_child_record_period
from ..harness.template_store import load_template
from ..schemas import FiveDomains, ThreeViewpoint
from ..schemas.template import SectionKind

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


def _section(label: str, content, width: float = _CONTENT_W) -> Table:
    """ラベル列＋内容列の1セクション行（帳票の基本ブロック）。content は Paragraph か flowable のリスト。

    width は本文幅（既定＝A4 縦。保育経過記録の年間マトリクスは A4 横なので横幅を渡す）。
    """
    tbl = Table(
        [[_P(label, _LABEL), content]],
        colWidths=[_LABEL_W, width - _LABEL_W],
        # 1欄の本文が1ページ高を超えても行内で分割して次ページへ流す（既定 splitInRow=0 だと分割点が
        # なく LayoutError で帳票生成が 500 になる）。長い総合所見・取込書類でも綴じられるようにする。
        splitInRow=1,
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
        splitInRow=1,  # 長い「子どもの姿」もページ跨ぎで分割（LayoutError 回避）
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
        _P(f"◆ {head}", _CHILD),  # _P が _t を1回かける（f-string 内で _t すると二重エスケープ）
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


# ── テンプレ駆動の線形本文レンダラ（帳票PDF・§18） ──
# 本文のセクション順序・見出しラベルは `template_store` の様式テンプレート（テキスト整形と共通の SSOT）を
# 歩いて描く。種別（SectionKind）→ ReportLab flowable の対応はここが持つ（テキストは draft.py が持つ＝
# 描画は各媒体・順序/ラベルは1つ）。ヘッダ合成・確認印欄・（要録の）グループ見出しは各 story wrapper のコード。
# 保育経過記録は年間マトリクス様式（線形でない）ため本レンダラは通さない（_child_record_story が担う）。


def _pdf_section_flowables(section, entry: dict, age: str) -> list:
    """テンプレの1セクションを帳票PDF の flowable リストに描く（種別で描画を切替）。"""
    kind = section.kind
    label = section.label
    key = section.key
    if kind is SectionKind.text_block:
        # 本文ブロックは空でも空セルで出す（プレースホルダはテキスト版のみ＝現行 PDF 挙動を保つ）。
        return [_section(label, _P(entry.get(key)))]
    if kind is SectionKind.text_inline:
        return [_section(label, _P(entry.get(key) or section.blank))]
    if kind is SectionKind.attendance:
        return [_section(label, _P(_attendance_text(entry.get(key))))]
    if kind is SectionKind.individual_notes:
        out: list = [Spacer(1, 2 * mm), _P(label, _LABEL), Spacer(1, 1.5 * mm)]
        notes = entry.get(key) or []
        life_record_always = age == "0-2"  # 0–2＝養護の中核として常時／3–5＝記入時のみ（§19）
        if notes:
            out.extend(_child_block(n, life_record_always) for n in notes)
        else:
            out.append(_section("", _P(section.blank)))
        return out
    if kind is SectionKind.tagged_list:
        # 各要素は「ねらい・内容/育ちの姿」＋「対応する姿・領域」の2行（item_field で見出しを切替）。
        item_label = "ねらい・内容" if section.item_field == "aim" else "育ちの姿"
        out = [Spacer(1, 2 * mm), _P(label, _LABEL), Spacer(1, 1.5 * mm)]
        items = entry.get(key) or []
        if items:
            for note in items:
                note = note or {}
                tags = note.get("tags") or []
                tag_text = "、".join(str(t) for t in tags) if tags else "（タグ未付与）"
                out.append(_section(item_label, _P(note.get(section.item_field), _SMALL)))
                out.append(_section("対応する姿・領域", _P(tag_text, _SMALL)))
                out.append(Spacer(1, 2 * mm))
        else:
            out.append(_section("", _P(section.blank)))
        return out
    if kind is SectionKind.evaluation2:
        ev = entry.get(key) or {}
        return [
            _section(f"{label} (a) 子どもに焦点", _P(ev.get("child_focus"))),
            _section(f"{label} (b) 自分の保育の適否", _P(ev.get("self_review"))),
        ]
    return []


def _linear_body(doc_type: str, entry: dict, age: str) -> list:
    """テンプレの本文セクションを順に flowable へ展開する（帳票PDF・線形様式の共通本体）。"""
    story: list = []
    for section in load_template(doc_type).sections:
        story.extend(_pdf_section_flowables(section, entry, age))
    return story


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
        *_linear_body("diary", entry, age),
        _signoff_block(),
    ]
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
        *_linear_body("monthly", entry, age),
        _signoff_block(),
    ]
    return story


# ── クラス月案＝園の実様式（月間指導計画・A4 横・§18） ──
# 園の実 Word 様式（monthly_*.docx＝A4 横）と同じ欄構成を帳票PDFで再現する：ヘッダ（年度・月/クラス/
# 担任・園長・主任の押印欄）→ 保育目標・先月の姿・行事・保護者支援 → 区分×領域グリッド（養護2本柱＋
# 教育5領域＝GRID_ROWS）→ 食育/健康・安全/家庭/職員の連携 →（0–2 のみ）個人目標小表 → 評価系欄（月末
# 記入の空欄）。描画のみ（型の保証は harness＝§5）。0–2/3–5 とも5領域グリッドで共通（§18）。

_CM_AGE_TITLE = {"0-2": "0〜2歳児", "3-5": "3歳以上児"}


def _cm_grid_table(grid: list) -> Table:
    """区分×領域グリッド（見出し＋7行）。列＝区分/領域/ねらい/環境・構成/子どもの姿/援助・配慮。"""
    label_w = 16 * mm
    domain_w = 24 * mm
    cell_w = (_L_CONTENT_W - label_w - domain_w) / 4
    header = [
        _P("区分", _LABEL),
        _P("領域", _LABEL),
        _P("ねらい", _LABEL),
        _P("環境・構成", _LABEL),
        _P("子どもの姿", _LABEL),
        _P("援助・配慮", _LABEL),
    ]
    rows: list[list] = [header]
    # 区分セルは連続する同一区分（養護/教育）で縦結合すると実様式に近い（SPAN で表現）。
    spans: list[tuple[int, int]] = []
    start = 1
    for i, row in enumerate(grid):
        row = row or {}
        rows.append(
            [
                _P(row.get("category"), _SMALL),
                _P(row.get("domain"), _SMALL),
                _P(row.get("aim"), _SMALL),
                _P(row.get("environment"), _SMALL),
                _P(row.get("child_state"), _SMALL),
                _P(row.get("support"), _SMALL),
            ]
        )
        nxt = (grid[i + 1] or {}).get("category") if i + 1 < len(grid) else None
        if row.get("category") != nxt:
            if i + 1 > start:  # 2行以上ある区分だけ縦結合
                spans.append((start, i + 1))
            start = i + 2
    tbl = Table(rows, colWidths=[label_w, domain_w, cell_w, cell_w, cell_w, cell_w])
    tbl.hAlign = "LEFT"
    style = [
        ("GRID", (0, 0), (-1, -1), 0.6, _LINE),
        ("BACKGROUND", (0, 0), (-1, 0), _HEADER_BG),
        ("BACKGROUND", (0, 1), (1, -1), _HEADER_BG),
        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]
    for r0, r1 in spans:
        style.append(("SPAN", (0, r0), (0, r1)))
    tbl.setStyle(TableStyle(style))
    return tbl


def _cm_kv_2x2(
    a_label: str, a_val, b_label: str, b_val, c_label: str, c_val, d_label: str, d_val
) -> Table:
    """ラベル|値 を 2×2 で並べる小表（食育/健康・安全 ・ 家庭/職員 の連携欄）。"""
    lw = 26 * mm
    vw = (_L_CONTENT_W - 2 * lw) / 2
    tbl = Table(
        [
            [_P(a_label, _LABEL), _P(a_val, _SMALL), _P(b_label, _LABEL), _P(b_val, _SMALL)],
            [_P(c_label, _LABEL), _P(c_val, _SMALL), _P(d_label, _LABEL), _P(d_val, _SMALL)],
        ],
        colWidths=[lw, vw, lw, vw],
    )
    tbl.hAlign = "LEFT"
    tbl.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.6, _LINE),
                ("BACKGROUND", (0, 0), (0, -1), _HEADER_BG),
                ("BACKGROUND", (2, 0), (2, -1), _HEADER_BG),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    return tbl


def _cm_individual_table(goals: list) -> Table:
    """個人目標小表（0–2）。列＝氏名（月齢）/子どもの姿/ねらい・配慮/評価・反省。評価は月末記入の空欄。"""
    name_w = 34 * mm
    eval_w = 46 * mm
    mid_w = (_L_CONTENT_W - name_w - eval_w) / 2
    header = [
        _P("氏名（月齢）", _LABEL),
        _P("子どもの姿", _LABEL),
        _P("ねらい・配慮", _LABEL),
        _P("評価・反省", _LABEL),
    ]
    rows: list[list] = [header]
    for g in goals:
        g = g or {}
        name = str(g.get("child_id") or "")
        months = str(g.get("age_months") or "").strip()
        if months:
            name = f"{name}（{months}）"
        rows.append(
            [
                _P(name, _SMALL),
                _P(g.get("child_state"), _SMALL),
                _P(g.get("aim_support"), _SMALL),
                _P(g.get("evaluation"), _SMALL),  # AI 非生成＝空欄（月末に手書き/記入）
            ]
        )
    tbl = Table(rows, colWidths=[name_w, mid_w, mid_w, eval_w])
    tbl.hAlign = "LEFT"
    tbl.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.6, _LINE),
                ("BACKGROUND", (0, 0), (-1, 0), _HEADER_BG),
                ("ALIGN", (0, 0), (-1, 0), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    return tbl


def _class_monthly_story(entry: dict) -> list:
    age = entry.get("age_band") or "0-2"
    # ── ヘッダ（年度・月／クラス／担任・園長・主任の押印欄＝実様式どおり手書き相当） ──
    class_name = str(entry.get("class_name") or "").strip()
    head = Table(
        [
            [
                _P(f"年度・月　{entry.get('month') or ''}", _BODY),  # _P が _t を1回かける
                _P(f"クラス　{class_name or '　　　　'}", _BODY),
                _P("担任　　　　　印", _LABEL),
                _P("園長　　　　　印", _LABEL),
                _P("主任　　　　　印", _LABEL),
            ]
        ],
        colWidths=[
            _L_CONTENT_W * 0.24,
            _L_CONTENT_W * 0.22,
            _L_CONTENT_W * 0.18,
            _L_CONTENT_W * 0.18,
            _L_CONTENT_W * 0.18,
        ],
    )
    head.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.6, _LINE),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    story: list = [
        _P(f"月間指導計画（月案）　{_CM_AGE_TITLE.get(age, age)}", _TITLE),
        Spacer(1, 2 * mm),
        head,
        Spacer(1, 2 * mm),
        _section("今月の保育目標", _P(entry.get("monthly_goal"), _SMALL), width=_L_CONTENT_W),
        _section("先月の子どもの姿", _P(entry.get("prev_month_state"), _SMALL), width=_L_CONTENT_W),
        _section("今月の行事", _P(entry.get("events") or "（なし）", _SMALL), width=_L_CONTENT_W),
        _section(
            "保護者支援", _P(entry.get("parent_support") or "（なし）", _SMALL), width=_L_CONTENT_W
        ),
        Spacer(1, 3 * mm),
        _P("指導計画（区分×領域）", _LABEL),
        Spacer(1, 1.5 * mm),
        _cm_grid_table(entry.get("grid") or []),
        Spacer(1, 3 * mm),
        _cm_kv_2x2(
            "食育",
            entry.get("syokuiku"),
            "健康・安全",
            entry.get("health_safety"),
            "家庭との連携",
            entry.get("family_liaison"),
            "職員間の連携",
            entry.get("staff_liaison"),
        ),
    ]
    # 個人目標小表（0–2 のみ・登場児ぶん）。3–5 は様式に無いので出さない。
    goals = entry.get("individual_goals") or []
    if goals:
        story += [
            Spacer(1, 3 * mm),
            _P("個人目標（月齢・一人ひとりに応じて）", _LABEL),
            Spacer(1, 1.5 * mm),
            _cm_individual_table(goals),
        ]
    # 評価系欄（月末に保育士が記入する運用欄＝空欄で描く）。
    story += [
        Spacer(1, 3 * mm),
        _cm_kv_2x2(
            "保育者の評価",
            entry.get("teacher_evaluation"),
            "子どもの評価",
            entry.get("children_evaluation"),
            "気になる子どもへの対応",
            entry.get("notable_children"),
            "",
            "",
        ),
    ]
    return story


# ── 保育経過記録＝年間マトリクス様式（現場の実様式に準拠・§19） ──
# 行＝領域（0–2:3つの視点／3–5:5領域＝告示準拠）＋「その他」、列＝4期（4〜6月/7〜9月/10〜12月/1〜3月）。
# 保育経過記録は年間1枚に期ごと追記していく運用（ヒアリング「3ヶ月に1回書く」）のため、帳票は年間シートとし、
# 今回の期の列に加え**同じ子・同じ年度の過去期の列を書類アーカイブ（record_store）から自動で埋める**
# （routes.py が引いて past_entries で渡す＝ここは割当と描画のみ）。アーカイブ未接続・該当なしは
# 従来どおり今回の期だけ＋他は空欄の罫線（手書き追記できる＝現場品質）。A4 横で描く。

_L_CONTENT_W = A4[1] - 2 * _MARGIN  # A4 横の本文幅（landscape で幅は A4 の長辺）
_QUARTER_LABELS = ["4月〜6月", "7月〜9月", "10月〜12月", "1月〜3月"]


def _P_multi(texts: list[str], style: ParagraphStyle = _SMALL) -> Paragraph:
    """複数の叙述を1セルに積む（各要素をエスケープして <br/> 連結。空はスペーサ行＝空欄の高さ確保）。"""
    body = "<br/><br/>".join(_t(t) for t in texts if str(t).strip())
    return Paragraph(body if body else "&nbsp;<br/>&nbsp;<br/>&nbsp;", style)


def assign_period_columns(entry: dict, past_entries: list[dict] | None = None) -> dict[int, dict]:
    """年間マトリクスの列（0〜3＝4期）へ entry を割り当てる純関数（テスト可能な割当の実体）。

    - 今回の entry は自分の期の列（period が読めなければ先頭列）に置き、**常に優先**する
      （アーカイブに同じ期の旧版があっても、いま出力しようとしている内容が正）。
    - past_entries（アーカイブ由来）は「同じ子・同じ年度・期が読める」ものだけ他の列へ置く。
      年度が違う/期が読めない/別の子は黙って除外（誤った列に描かない）。同じ列に複数来たら後勝ち
      （record_store が期間順で返す＝新しい期間表記が残る）。
    """
    current_period = parse_child_record_period(str(entry.get("period") or ""))
    quarter = current_period.quarter - 1 if current_period else 0
    columns: dict[int, dict] = {}
    fiscal = current_period.fiscal_year if current_period else None
    child = str(entry.get("child_id") or "").strip()
    if fiscal is not None:
        for past in past_entries or []:
            if not isinstance(past, dict):
                continue
            past_child = str(past.get("child_id") or "").strip()
            if child and past_child and past_child != child:
                continue
            past_period = parse_child_record_period(str(past.get("period") or ""))
            if past_period is None or past_period.fiscal_year != fiscal:
                continue
            columns[past_period.quarter - 1] = past
    columns[quarter] = entry  # 今回の期が常に勝つ
    return columns


def _entry_cells(entry: dict, row_labels: list[str]) -> dict[str, list[str]]:
    """1期分の entry を行（領域）別の叙述リストへ振り分ける（最初に一致した枠組みタグの行へ。無ければ「その他」）。"""
    cells: dict[str, list[str]] = {label: [] for label in row_labels}
    for note in entry.get("development_notes") or []:
        note = note or {}
        tags = [str(t) for t in (note.get("tags") or [])]
        row = next((label for label in row_labels[:-1] if label in tags), "その他")
        desc = str(note.get("description") or "").strip()
        if desc:
            cells[row].append(desc)
    care = str(entry.get("care_notes") or "").strip()
    if care:
        cells["その他"].append(f"【配慮・特記】{care}")
    return cells


def _child_record_story(
    entry: dict, past_entries: list[dict] | None = None, official_name: str | None = None
) -> list:
    """保育経過記録＝年間マトリクス（行＝領域×列＝4期）。各列に該当期の development_notes をタグで振り分けて描く。

    行ラベルは告示準拠（0–2＝3つの視点／3–5＝5領域）＋「その他」（枠組みタグの無い叙述と配慮・特記を集約）。
    今回の期に加え、past_entries（アーカイブの同じ子・同じ年度の保育経過記録）で他の期の列も埋める＝年間1枚が
    期を追うごとに育つ。行ラベルは**今回の entry の年齢帯**で固定（年度途中の帯替わりは §18 の実様式微調整）。
    身長・体重は原簿系の任意欄（AI は生成しない＝保育士が編集フォームで記入 or 手書き）。総合所見・家庭連携・
    次期に向けては**今回の期の記載**として表の下に全幅で添える。
    """
    age = entry.get("age_band") or "0-2"
    row_labels = [e.value for e in (FiveDomains if age == "3-5" else ThreeViewpoint)] + ["その他"]

    period = str(entry.get("period") or "")
    parsed_period = parse_child_record_period(period)
    fiscal = f"{parsed_period.fiscal_year}年度" if parsed_period else ""

    # 列（4期）ごとに割当 entry の行別セルを作る（割当の実体は assign_period_columns＝純関数）。
    columns = assign_period_columns(entry, past_entries)
    col_cells = {qi: _entry_cells(e, row_labels) for qi, e in columns.items()}

    # ── ヘッダ（年度・クラス・タイトル／担任印。児童名・生年月日欄は実様式どおり＝生年月日は手書き） ──
    # 児童名欄は本名（姓＋名）を優先＝official_name（児童マスタ由来・AI 非生成）。未登録は呼び名へ降格。
    subject = official_name or entry.get("child_id") or "（対象児）"
    months = str(entry.get("age_months") or "").strip()
    head = Table(
        [
            [
                _P(
                    f"{fiscal or '　　　　年度'}　{_AGE_LABEL.get(age, age)}クラス　保育経過記録",
                    _TITLE,
                ),
                _P("担任　　　　　　　　　印", _LABEL),
            ],
            [
                _P(
                    f"児童名　{subject}" + (f"（{months}）" if months else ""), _BODY
                ),  # _P が _t を1回
                _P("　　　　年　　月　　日 生まれ", _LABEL),
            ],
        ],
        colWidths=[_L_CONTENT_W * 0.62, _L_CONTENT_W * 0.38],
    )
    head.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
                ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ]
        )
    )

    # ── マトリクス本体（ラベル列＋4期列。割当のある期の列に内容が入る・他は空欄の罫線） ──
    label_w = 24 * mm
    col_w = (_L_CONTENT_W - label_w) / 4
    header_row = [_P("子どもの姿（園での様子）", _LABEL)] + [_P(q, _LABEL) for q in _QUARTER_LABELS]
    matrix: list[list] = [header_row]
    for label in row_labels:
        row: list = [_P(label, _LABEL)]
        for qi in range(4):
            row.append(_P_multi(col_cells[qi][label] if qi in col_cells else []))
        matrix.append(row)
    # 身長・体重（原簿系の任意欄。値があればその期の列に、無ければ単位だけ＝手書き用）
    for label, key, unit in (("身長", "height_cm", "cm"), ("体重", "weight_kg", "kg")):
        row = [_P(label, _LABEL)]
        for qi in range(4):
            value = str(columns.get(qi, {}).get(key) or "").strip()
            text = f"{value} {unit}" if value else unit
            p = Paragraph(_t(text), _SMALL)
            row.append(p)
        matrix.append(row)

    # splitInRow=1＝1領域（行）の期セルが長文でも行内分割で次ページへ流す（LayoutError 回避）。
    tbl = Table(matrix, colWidths=[label_w] + [col_w] * 4, splitInRow=1)
    tbl.hAlign = "LEFT"
    tbl.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.6, _LINE),
                ("BACKGROUND", (0, 0), (-1, 0), _HEADER_BG),
                ("BACKGROUND", (0, 1), (0, -1), _HEADER_BG),
                ("ALIGN", (0, 0), (-1, 0), "CENTER"),
                ("ALIGN", (1, -2), (-1, -1), "RIGHT"),  # 身長・体重は右寄せ（実様式）
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )

    filled_note = "（該当する期の列に記載）"
    if len(columns) > 1:
        filled_note = "（過去の期は保存済みの保育経過記録から記載）"
    story: list = [
        head,
        Spacer(1, 2 * mm),
        _P(f"今回の記入: {period or '（対象期間 未指定）'}{filled_note}", _META),  # _P が _t を1回
        Spacer(1, 1.5 * mm),
        tbl,
        Spacer(1, 3 * mm),
        _section("総合所見", _P(entry.get("overall_note"), _SMALL), width=_L_CONTENT_W),
        _section(
            "家庭との連携",
            _P(entry.get("family_liaison") or "（なし）", _SMALL),
            width=_L_CONTENT_W,
        ),
        _section(
            "次期に向けて", _P(entry.get("next_aims") or "（なし）", _SMALL), width=_L_CONTENT_W
        ),
    ]
    return story


# ── 保育要録＝保育所児童保育要録（保育に関する記録・§19・L4） ──
# 全国統一様式（こども家庭庁の参考例）は3列（氏名/性別/5領域ねらい｜保育の過程と子どもの育ち｜
# 最終年度に至るまでの育ち）。左列は原簿系＋固定参照なので、帳票は harness の write_nursery_record_draft と
# 同じ章立てで A4 縦に積む（最終年度の重点→個人の重点→保育の展開〔5領域/10の姿タグ〕→特に配慮すべき事項
# →最終年度に至るまでの育ち）＝現場でそのまま綴じられる体裁にする。描画のみ（型の保証は harness＝§5）。


def _nursery_record_story(entry: dict, official_name: str | None = None) -> list:
    age = entry.get("age_band") or "3-5"
    # 氏名欄は本名（姓＋名）を優先＝就学先引継ぎの公式様式。未登録は呼び名（child_id）へ降格。
    subject = official_name or entry.get("child_id") or "（対象児）"
    months = str(entry.get("age_months") or "").strip()
    if months:
        subject = f"{subject}（{months}）"
    meta_bits = [
        f"対象年度: {entry.get('fiscal_year') or ''}",
        f"対象児: {subject}",
        f"クラス: {_AGE_LABEL.get(age, age)}",
    ]
    school = str(entry.get("school_name") or "").strip()
    if school:
        meta_bits.append(f"就学先: {school}")
    period = str(entry.get("enrollment_period") or "").strip()
    if period:
        meta_bits.append(f"保育期間: {period}")
    # 本文（最終年度の重点→個人の重点→保育の展開→特に配慮→最終年度に至るまで）はテンプレ駆動。
    # 「保育の過程と子どもの育ちに関する事項」は本文群のグループ見出し＝コード側の chrome として前置する。
    story: list = [
        _P("保育所児童保育要録（保育に関する記録）", _TITLE),
        _P("　　".join(meta_bits), _META),
        Spacer(1, 3 * mm),
        _P("保育の過程と子どもの育ちに関する事項", _LABEL),
        Spacer(1, 1.5 * mm),
        *_linear_body("nursery_record", entry, age),
        _signoff_block(),
    ]
    return story


_BUILDERS = {
    "diary": _diary_story,
    "monthly": _monthly_story,
    "class_monthly": _class_monthly_story,
    "child_record": _child_record_story,
    "nursery_record": _nursery_record_story,
}

# A4 横で描く様式（園フォームの向きに一致）：保育経過記録（年間マトリクス）＋クラス月案（月間指導計画）。
_LANDSCAPE_KINDS = {"child_record", "class_monthly"}


def render_pdf(
    kind: str,
    entry: dict,
    past_entries: list[dict] | None = None,
    official_name: str | None = None,
) -> bytes:
    """確定 entry（dict）を帳票PDF（bytes）へ描画する。
    kind = "diary" | "monthly" | "class_monthly" | "child_record" | "nursery_record"。

    past_entries は保育経過記録のみ有効＝同じ子の保存済み保育経過記録（アーカイブ由来）。同じ年度のものだけ
    年間マトリクスの他の期の列に埋める（割当は assign_period_columns・今回の entry が常に優先）。
    official_name は保育経過記録/保育要録の**氏名欄**に描く本名（姓＋名・児童マスタ由来・AI 非生成）＝
    未指定は呼び名（child_id）へ降格。日誌/月案/クラス月案は使わない（呼び名のまま）。
    描画のみ（型検査はしない＝空欄は空セルで出す）。entry が dict でない・kind 不正は ValueError。
    """
    if kind not in _BUILDERS:
        raise ValueError(
            f"未知の kind: {kind!r}"
            "（'diary' | 'monthly' | 'class_monthly' | 'child_record' | 'nursery_record'）"
        )
    if not isinstance(entry, dict):
        raise ValueError("entry は dict である必要があります")
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        # 保育経過記録（年間マトリクス）・クラス月案（月間指導計画）は園フォームが A4 横なので横で描く。他は A4 縦。
        pagesize=landscape(A4) if kind in _LANDSCAPE_KINDS else A4,
        leftMargin=_MARGIN,
        rightMargin=_MARGIN,
        topMargin=_MARGIN,
        bottomMargin=_MARGIN,
        title={
            "diary": "保育日誌",
            "monthly": "個別月案",
            "class_monthly": "月間指導計画（クラス月案）",
            "child_record": "保育経過記録",
            "nursery_record": "保育所児童保育要録",
        }[kind],
    )
    if kind == "child_record":
        story = _child_record_story(entry, past_entries, official_name)
    elif kind == "nursery_record":
        story = _nursery_record_story(entry, official_name)
    else:
        story = _BUILDERS[kind](entry)
    try:
        doc.build(story)
    except LayoutError as e:
        # splitInRow で大半は次ページへ流れるが、単一セル本文が1ページ高を超える等の病的入力では
        # なお LayoutError になりうる。生の 500 でなく意味の通る ValueError にして route が 400 化する。
        raise ValueError("本文が長すぎて帳票の1ページに収まりません（内容を分けてください）") from e
    return buf.getvalue()
