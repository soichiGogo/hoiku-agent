"""保育要録 harness（validate_nursery_record_fields / write_nursery_record_draft / finalize）の単体テスト。

設計コンテキスト §19（保育要録＝集積階層の最終段 L4・最終年度の保育経過記録を集積）/ §16（決定的ロジックは
pytest 必須）。LLM 非依存・高速。保育経過記録（test_child_record.py）と対称の検査を要録でも担保する。
要録は年長（5歳児）専用のため年齢分岐は実質 5領域に畳まれる（共通の _required_tag_type を流用）。
"""

from __future__ import annotations

import json

from hoiku_agent.harness import (
    child_record_digest,
    finalize_nursery_record_document,
    format_record_digest_for_prompt,
    validate_nursery_record_fields,
    write_nursery_record_draft,
)
from hoiku_agent.schemas import ChildRecord as _ChildRecord
from hoiku_agent.schemas import (
    AgeBand,
    DevelopmentNote,
    FiveDomains,
    NurseryRecord,
    ThreeViewpoint,
)


def _record(
    *,
    development_notes: list | None = None,
    fiscal_year: str = "2026",
    child_id: str = "架空児A",
    final_year_focus: str = "共通の目的に向かって思いや考えを出し合いながら活動を楽しむ",
    individual_focus: str = "生活や遊びの中で、自分を発揮しながらさまざまな活動を楽しむ",
    growth_until_final: str = "入園当初は不安が大きかったが、生活のリズムが身につき生き生きと表現を楽しむ姿へ育った",
) -> NurseryRecord:
    if development_notes is None:
        development_notes = [
            DevelopmentNote(
                description="友だちと鉄棒ややなぎ棒にも挑戦するようになってきた",
                tags=[FiveDomains.健康],
            ),
            DevelopmentNote(
                description="自分の思いを表現しようとする姿に成長を感じた",
                tags=[FiveDomains.表現],
            ),
        ]
    return NurseryRecord(
        fiscal_year=fiscal_year,
        age_band=AgeBand.三から五歳,
        child_id=child_id,
        final_year_focus=final_year_focus,
        individual_focus=individual_focus,
        development_notes=development_notes,
        growth_until_final=growth_until_final,
    )


# ──────────────────────── validate_nursery_record_fields ────────────────────────


def test_valid_nursery_record_passes():
    assert validate_nursery_record_fields(_record()) == []


def test_nursery_record_requires_five_domains_tag():
    """年長（5歳児）の保育の展開は5領域タグが必須（3つの視点だけでは違反）。"""
    notes = [DevelopmentNote(description="x", tags=[ThreeViewpoint.健やかに伸び伸びと育つ])]
    problems = validate_nursery_record_fields(_record(development_notes=notes))
    assert any("5領域" in p for p in problems)


def test_nursery_record_rejects_0_2_age_band():
    """要録は年長（3–5歳児クラス＝5領域）専用。0–2 で3つの視点タグを持たせても型不成立にする（§19）。"""
    rec = _record()
    object.__setattr__(rec, "age_band", AgeBand.零から二歳)
    object.__setattr__(
        rec,
        "development_notes",
        [DevelopmentNote(description="x", tags=[ThreeViewpoint.健やかに伸び伸びと育つ])],
    )
    problems = validate_nursery_record_fields(rec)
    assert any("年長" in p and "0-2" in p for p in problems)


def test_nursery_record_missing_required_fields_are_violations():
    problems = validate_nursery_record_fields(
        _record(
            fiscal_year="  ",
            child_id="",
            final_year_focus="",
            individual_focus="",
            growth_until_final="",
            development_notes=[],
        )
    )
    assert any("対象年度" in p for p in problems)
    assert any("対象児" in p for p in problems)
    assert any("最終年度の重点" in p for p in problems)
    assert any("個人の重点" in p for p in problems)
    assert any("最終年度に至るまでの育ち" in p for p in problems)
    assert any("保育の展開と子どもの育ち" in p for p in problems)


def test_nursery_record_special_notes_optional():
    """特に配慮すべき事項は任意（様式上「なし」がありうる）＝空でも充足。"""
    rec = _record()
    assert rec.special_notes == ""
    assert validate_nursery_record_fields(rec) == []


# ──────────────────────── write_nursery_record_draft ────────────────────────


def test_write_nursery_record_draft_renders_sections_and_tags():
    text = write_nursery_record_draft(_record())
    for section in [
        "保育所児童保育要録",
        "最終年度の重点",
        "個人の重点",
        "保育の展開と子どもの育ち",
        "特に配慮すべき事項",
        "最終年度に至るまでの育ちに関する事項",
    ]:
        assert section in text
    # 枠組みタグを明示出力する（§13 のドメイン作り込み）。
    assert "健康" in text and "表現" in text
    assert "2026" in text and "架空児A" in text


def test_write_nursery_record_draft_special_notes_defaults_to_none_label():
    """特に配慮すべき事項が空なら様式上「なし」と描く。"""
    text = write_nursery_record_draft(_record())
    assert "【特に配慮すべき事項】 なし" in text


# ──────────────────────── finalize_nursery_record_document ────────────────────────


def test_finalize_nursery_record_success_path():
    """JSON フェンス入りの要録ドラフト→復元・検査通過・整形出力。"""
    draft = "保育要録の下書きです。\n```json\n" + _record().model_dump_json() + "\n```"
    result = finalize_nursery_record_document(draft)
    assert result.parse_error is None
    assert result.problems == []
    assert result.formatted and "最終年度に至るまでの育ち" in result.formatted
    assert result.ok


def test_finalize_nursery_record_parse_error_when_no_json():
    result = finalize_nursery_record_document("情報不足で作成できませんでした。")
    assert result.parse_error
    assert not result.ok


def test_finalize_nursery_record_surfaces_validation_problems():
    """5領域タグ不足→parse は成功・problems 非空・整形は生成（人が直す）。"""
    record = _record(
        development_notes=[DevelopmentNote(description="x", tags=[])]  # タグ無し
    )
    draft = "```json\n" + record.model_dump_json() + "\n```"
    result = finalize_nursery_record_document(draft)
    assert result.parse_error is None
    assert any("5領域" in p for p in result.problems)
    assert result.formatted
    assert not result.ok


def test_finalize_nursery_record_dict_roundtrip():
    """素の dict→json でも復元できる（LLM 出力の揺れ耐性）。"""
    payload = json.loads(_record().model_dump_json())
    draft = "```json\n" + json.dumps(payload, ensure_ascii=False) + "\n```"
    assert finalize_nursery_record_document(draft).ok


# ──────────────────────── child_record_digest（L4 還流の集計） ────────────────────────


def _cr(period: str, tag, desc: str, overall: str) -> _ChildRecord:
    return _ChildRecord(
        period=period,
        age_band=AgeBand.三から五歳,
        child_id="架空児A",
        development_notes=[DevelopmentNote(description=desc, tags=[tag])],
        overall_note=overall,
    )


def test_child_record_digest_aggregates_by_child_and_period():
    """最終年度の保育経過記録を child_id 別・期順に集計し、領域頻度・発達叙述・総合所見を事実として集める。"""
    records = [
        _cr("2026-04〜2026-06", FiveDomains.健康, "運動遊びに親しんだ", "自分を発揮し始めた"),
        _cr("2026-07〜2026-09", FiveDomains.人間関係, "友だちと協力した", "関わりが広がった"),
    ]
    digest = child_record_digest(records)
    assert set(digest) == {"架空児A"}
    slot = digest["架空児A"]
    assert slot["record_count"] == 2
    assert slot["periods"] == ["2026-04〜2026-06", "2026-07〜2026-09"]
    assert slot["tag_freq"] == {"健康": 1, "人間関係": 1}
    assert len(slot["development"]) == 2 and len(slot["overall_notes"]) == 2


def test_child_record_digest_empty_and_format_degrades():
    assert child_record_digest([]) == {}
    text = format_record_digest_for_prompt({}, label="最終年度")
    assert "保育経過記録データがありません" in text


def test_format_record_digest_lists_facts():
    records = [_cr("2026-04〜2026-06", FiveDomains.表現, "劇遊びを楽しんだ", "表現が豊かになった")]
    text = format_record_digest_for_prompt(child_record_digest(records))
    assert "架空児A" in text and "劇遊びを楽しんだ" in text and "表現×1" in text
