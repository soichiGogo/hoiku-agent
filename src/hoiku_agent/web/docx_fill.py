"""確定 entry（final_entry）→ 園の実 Word 様式（.docx）への流し込み（層A/web の presentation）。

設計コンテキスト §11（配信UI）／ §18（“園の様式で出す”最終形）。`chohyo_pdf.py`（ReportLab で
帳票PDF を描く）と対になる出力経路で、**園が実際に使っている Word フォーム（`web/templates/*.docx`）**を
そのまま雛形にして、確定 entry の値を該当セルへ流し込み、編集可能な .docx として返す。保育士は
Word で開いて微修正・印刷・PDF 化できる（＝Word が母艦の現場に寄せる）。**描画（流し込み）だけ**で、
必須欄・年齢分岐等の型の保証は harness が持つ（§5・ここは validation を持たない）。

依存は **python-docx（純 pip・システムライブラリ不要＝Dockerfile 不変）**。雛形 .docx は `web/templates/` に
同梱し実行時に外部取得しない（ローカル完結）。docx→PDF の**サーバ変換はしない**（LibreOffice 等の
重い依存を持ち込まない＝確定・綴じ用の PDF は `chohyo_pdf.py` が担い、Word 編集用は本モジュールが担う）。

現状スライス（PoC）＝**児童票（保育経過記録）**のみ配線。園フォームは 5領域×子どもの姿 の様式なので
生成対象は 3–5（5領域）。月案（クラス月案の個人目標小表へ写像）・保育要録は後続スライスで足す
（`_FILLERS` に kind を追加するだけで拡張できる形にしてある）。
"""

from __future__ import annotations

import io
import re
from pathlib import Path

from docx import Document
from docx.table import Table

from ..schemas import FiveDomains

_TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"

# 園フォームの5領域行の見出し（テンプレの table 見出しと一致・順序はテンプレ側に従う）。
_FIVE_DOMAINS = {e.value for e in FiveDomains}


def _set_cell(cell, text: str) -> None:
    """セルの本文を text に置き換える（段落プロパティは残し、runs だけ差し替える＝書式温存寄り）。

    python-docx の `cell.text = ...` は段落・runs を丸ごと単一 run へ潰すため、既存の配置/フォント指定が
    失われやすい。ここでは最初の段落の runs をクリアして1つの run を足すに留め、空欄の書式を壊しにくくする。
    """
    para = cell.paragraphs[0]
    for run in list(para.runs):
        run.text = ""
    if para.runs:
        para.runs[0].text = text
    else:
        para.add_run(text)


def _find_table(doc: Document, *, header_contains: tuple[str, ...]) -> Table | None:
    """先頭行のセル文言に header_contains の語をすべて含む表を返す（署名でテンプレ表を同定）。

    セル位置のハードコードでなく見出し語で表を見つける＝テンプレの前後に表が増減しても壊れにくい。
    """
    for tbl in doc.tables:
        if not tbl.rows:
            continue
        head = "".join(c.text for c in tbl.rows[0].cells)
        if all(tok in head for tok in header_contains):
            return tbl
    return None


def _label_row_value_cell(tbl: Table, label: str):
    """表内で1列目が label のちょうどそのセル（＝流し込み先の2列目）を返す。無ければ None。

    児童票の「領域×子どもの姿」表のように 1列目＝ラベル / 最終列＝記入 の様式を素直に扱う。
    """
    for row in tbl.rows:
        cells = row.cells
        if cells and cells[0].text.strip() == label:
            return cells[-1]
    return None


def _fiscal_year_label(period: str) -> str:
    """対象期間の自由記述先頭から年度（4月始まり）を推定して「YYYY年度」を返す。読めなければ空。"""
    m = re.search(r"(\d{4})\s*[-/年]\s*(\d{1,2})", str(period or ""))
    if not m:
        return ""
    year, month = int(m.group(1)), int(m.group(2))
    if not (1 <= month <= 12):
        return ""
    fiscal = year if month >= 4 else year - 1
    return f"{fiscal}年度"


_AGE_LABEL = {"0-2": "0〜2", "3-5": "3〜5"}


def _fill_child_record(entry: dict) -> Document:
    """児童票（保育経過記録）フォームへ確定 entry を流し込む。

    - ヘッダ表：児童名・年度（対象期間から推定）・歳児（年齢帯）。生年月日・担任印は手書き欄のまま。
    - 対象期間表：period をそのまま。
    - 領域×子どもの姿表：development_notes を 5領域タグで各行に振り分け（複数は改行連結）。
      5領域タグを持たない叙述（3つの視点・10の姿のみ等）はこの様式に置き場が無いので流し込まない
      （PDF/テキスト版には出る）＝様式に無いものを勝手に作らない。
    """
    doc = Document(str(_TEMPLATE_DIR / "child_record.docx"))

    # ── ヘッダ（年度／歳児／児童名） ──
    header = _find_table(doc, header_contains=("年度", "歳児", "担任"))
    if header is not None:
        cells = header.rows[0].cells
        # r0: [年度, <値>, 歳児, <値>, 担任, <値>, 印]
        _set_cell(cells[1], _fiscal_year_label(str(entry.get("period") or "")))
        _set_cell(cells[3], _AGE_LABEL.get(entry.get("age_band") or "3-5", ""))
        # r1: [児童名, <値(結合)>, …, 生年月日, …]。最終列が生年月日の手書き欄なので _label_row_value_cell は
        # 使わず（それは最終列を返す）、児童名ラベル直後の結合セル（index1）へ入れる。
        if len(header.rows) > 1:
            _set_cell(header.rows[1].cells[1], str(entry.get("child_id") or ""))

    # ── 対象期間 ──
    period_tbl = _find_table(doc, header_contains=("対象期間",))
    if period_tbl is not None:
        cell = _label_row_value_cell(period_tbl, "対象期間")
        if cell is not None:
            _set_cell(cell, str(entry.get("period") or ""))

    # ── 領域×子どもの姿（AI 内容の本体） ──
    matrix = _find_table(doc, header_contains=("領域", "子どもの姿"))
    if matrix is not None:
        by_domain: dict[str, list[str]] = {d: [] for d in _FIVE_DOMAINS}
        for note in entry.get("development_notes") or []:
            note = note or {}
            desc = str(note.get("description") or "").strip()
            if not desc:
                continue
            for tag in note.get("tags") or []:
                if str(tag) in by_domain:
                    by_domain[str(tag)].append(desc)
        for row in matrix.rows[1:]:  # 見出し行を除く
            label = row.cells[0].text.strip()
            if label in by_domain and by_domain[label]:
                _set_cell(row.cells[-1], "\n".join(by_domain[label]))

    return doc


# kind → (filler, 表示名)。新しい書類は filler を足すだけで拡張できる。
_FILLERS = {
    "child_record": _fill_child_record,
}


def supported_kinds() -> list[str]:
    """docx 流し込みに対応済みの kind 一覧（UI が Word ダウンロードボタンの出し分けに使う）。"""
    return list(_FILLERS)


def fill_docx(kind: str, entry: dict) -> bytes:
    """確定 entry（dict）を園の実 Word 様式へ流し込み、.docx の bytes を返す。

    未対応 kind・entry が dict でない場合は ValueError（route が 400 で可視化・握りつぶさない）。
    描画のみ（型検査はしない＝空欄は空セルのまま。型の保証は harness＝§5）。
    """
    filler = _FILLERS.get(kind)
    if filler is None:
        raise ValueError(f"docx 未対応の kind: {kind!r}（対応: {', '.join(_FILLERS) or 'なし'}）")
    if not isinstance(entry, dict):
        raise ValueError("entry は dict である必要があります")
    doc = filler(entry)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()
