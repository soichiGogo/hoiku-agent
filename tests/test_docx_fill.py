"""web.docx_fill の単体テスト（LLM 非依存）。

園の実 Word 様式（`web/templates/*.docx`）へ確定 entry を流し込む presentation 層の描画を検証する。
型検査は harness の責務なので、ここは「値が正しいセルに入るか／未対応は落ちるか」だけを見る（§5）。
chohyo_pdf のテスト（tests/test_chohyo_pdf.py）と対になる。
"""

from __future__ import annotations

import io

import docx
import pytest

from hoiku_agent.schemas import AgeBand, ChildRecord, DevelopmentNote, FiveDomains
from hoiku_agent.web.docx_fill import fill_docx, supported_kinds


def _record() -> dict:
    return ChildRecord(
        period="2026-04〜2026-06",
        age_band=AgeBand.三から五歳,
        child_id="ゆいちゃん",
        development_notes=[
            DevelopmentNote(
                description="好きな遊びに自分から関わる姿が増えた", tags=[FiveDomains.健康]
            ),
            DevelopmentNote(
                description="順番を待つ場面が見られるようになった", tags=[FiveDomains.人間関係]
            ),
        ],
        overall_note="安心を土台に遊びの世界を広げている",
    ).model_dump(mode="json")


def _tables(data: bytes) -> list:
    return docx.Document(io.BytesIO(data)).tables


def test_supported_kinds_has_child_record():
    assert "child_record" in supported_kinds()


def test_fill_child_record_returns_docx_bytes():
    data = fill_docx("child_record", _record())
    assert data[:2] == b"PK"  # docx = zip
    assert len(data) > 0


def test_fill_child_record_places_content_by_domain():
    """development_notes が 5領域タグごとに「領域×子どもの姿」表の該当行へ入る。"""
    tables = _tables(fill_docx("child_record", _record()))
    matrix = next(t for t in tables if "領域" in t.rows[0].cells[0].text)
    rows = {r.cells[0].text.strip(): r.cells[-1].text for r in matrix.rows[1:]}
    assert "好きな遊びに自分から関わる姿が増えた" in rows["健康"]
    assert "順番を待つ場面が見られるようになった" in rows["人間関係"]
    # タグの無い領域は空欄のまま（様式に無いものを勝手に作らない）。
    assert rows["環境"].strip() == ""


def test_fill_child_record_fills_header_and_period():
    tables = _tables(fill_docx("child_record", _record()))
    header = next(t for t in tables if "児童名" in "".join(c.text for c in t.rows[1].cells))
    assert "ゆいちゃん" in "".join(c.text for c in header.rows[1].cells)
    assert "2026年度" in "".join(c.text for c in header.rows[0].cells)  # 対象期間から年度推定
    period_tbl = next(t for t in tables if t.rows[0].cells[0].text.strip() == "対象期間")
    assert "2026-04〜2026-06" in period_tbl.rows[0].cells[-1].text


def test_fill_unknown_kind_raises():
    with pytest.raises(ValueError):
        fill_docx("diary", _record())


def test_fill_non_dict_raises():
    with pytest.raises(ValueError):
        fill_docx("child_record", "not a dict")  # type: ignore[arg-type]
