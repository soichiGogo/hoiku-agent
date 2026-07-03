"""児童票 harness（validate_child_record_fields / write_child_record_draft / finalize / prep）の単体テスト。

設計コンテキスト §19（児童票＝期ごとの保育経過記録・L3 還流）/ §16（決定的ロジックは pytest 必須）。
LLM 非依存・高速。月案（test_monthly.py）と対称の検査を児童票でも担保する。
DigestPrepAgent の入出力キー一般化（月案既定キーの後方互換）もここで検証する。
"""

from __future__ import annotations

import json

from hoiku_agent.harness import (
    finalize_child_record_document,
    validate_child_record_fields,
    write_child_record_draft,
)
from hoiku_agent.harness.monthly import DigestPrepAgent
from hoiku_agent.schemas import (
    AgeBand,
    ChildRecord,
    DevelopmentNote,
    FiveDomains,
    ThreeViewpoint,
)


def _record(
    *,
    age_band: AgeBand = AgeBand.零から二歳,
    development_notes: list | None = None,
    period: str = "2026-04〜2026-06",
    child_id: str = "架空児A",
    overall_note: str = "安心できる関係を土台に、自分から環境に関わる姿が増えた",
) -> ChildRecord:
    if development_notes is None:
        development_notes = [
            DevelopmentNote(
                description="伝い歩きから一人歩きへ移行し、探索範囲が広がった",
                tags=[ThreeViewpoint.健やかに伸び伸びと育つ],
            )
        ]
    return ChildRecord(
        period=period,
        age_band=age_band,
        child_id=child_id,
        development_notes=development_notes,
        overall_note=overall_note,
    )


# ──────────────────────── validate_child_record_fields ────────────────────────


def test_valid_child_record_passes():
    assert validate_child_record_fields(_record()) == []


def test_child_record_0_2_requires_three_viewpoint_tag():
    """0–2 の発達の経過に3つの視点タグが無ければ違反。"""
    notes = [DevelopmentNote(description="x", tags=[])]
    assert any(
        "3つの視点" in p for p in validate_child_record_fields(_record(development_notes=notes))
    )


def test_child_record_3_5_requires_five_domains_tag():
    """3–5 は5領域タグが必須（3つの視点だけでは違反）＝全年齢対応の年齢分岐。"""
    notes = [DevelopmentNote(description="x", tags=[ThreeViewpoint.健やかに伸び伸びと育つ])]
    problems = validate_child_record_fields(
        _record(age_band=AgeBand.三から五歳, development_notes=notes)
    )
    assert any("5領域" in p for p in problems)


def test_child_record_3_5_with_five_domains_passes():
    notes = [
        DevelopmentNote(
            description="友だちとルールのある遊びを楽しんだ", tags=[FiveDomains.人間関係]
        )
    ]
    assert (
        validate_child_record_fields(_record(age_band=AgeBand.三から五歳, development_notes=notes))
        == []
    )


def test_child_record_missing_required_fields_are_violations():
    problems = validate_child_record_fields(
        _record(period="  ", child_id="", overall_note="", development_notes=[])
    )
    assert any("対象期間" in p for p in problems)
    assert any("対象児" in p for p in problems)
    assert any("総合所見" in p for p in problems)
    assert any("発達の経過" in p for p in problems)


# ──────────────────────── write_child_record_draft ────────────────────────


def test_write_child_record_draft_renders_sections_and_tags():
    text = write_child_record_draft(_record())
    for section in [
        "児童票・保育経過記録",
        "発達の経過",
        "配慮事項・特記",
        "家庭との連携",
        "総合所見",
        "次期に向けて",
    ]:
        assert section in text
    # 枠組みタグを明示出力する（§13 のドメイン作り込み）。
    assert "健やかに伸び伸びと育つ" in text
    assert "2026-04〜2026-06" in text and "架空児A" in text


# ──────────────────────── finalize_child_record_document ────────────────────────


def test_finalize_child_record_success_path():
    """JSON フェンス入りの児童票ドラフト→復元・検査通過・整形出力。"""
    draft = "児童票の下書きです。\n```json\n" + _record().model_dump_json() + "\n```"
    result = finalize_child_record_document(draft)
    assert result.parse_error is None
    assert result.problems == []
    assert result.formatted and "総合所見" in result.formatted
    assert result.ok


def test_finalize_child_record_parse_error_when_no_json():
    result = finalize_child_record_document("情報不足で作成できませんでした。")
    assert result.parse_error
    assert not result.ok


def test_finalize_child_record_surfaces_validation_problems():
    """年齢分岐タグ不足→parse は成功・problems 非空・整形は生成（人が直す）。"""
    record = _record(
        development_notes=[DevelopmentNote(description="x", tags=[FiveDomains.表現])]  # 0–2 に5領域
    )
    draft = "```json\n" + record.model_dump_json() + "\n```"
    result = finalize_child_record_document(draft)
    assert result.parse_error is None
    assert any("3つの視点" in p for p in result.problems)
    assert result.formatted
    assert not result.ok


def test_finalize_child_record_dict_roundtrip():
    """素の dict→json でも復元できる（LLM 出力の揺れ耐性）。"""
    payload = json.loads(_record().model_dump_json())
    draft = "```json\n" + json.dumps(payload, ensure_ascii=False) + "\n```"
    assert finalize_child_record_document(draft).ok


# ──────────────────────── DigestPrepAgent（キー一般化） ────────────────────────


def test_digest_prep_agent_defaults_keep_monthly_keys():
    """既定キーは月案（prev_month_entries → prev_month_digest）＝後方互換。"""
    agent = DigestPrepAgent(name="monthly_prep")
    assert agent.input_key == "prev_month_entries"
    assert agent.output_key == "prev_month_digest"
    assert agent.digest_label == "前月"


def test_digest_prep_agent_accepts_period_keys():
    """児童票（L3 還流）は period_entries → period_digest を配線できる。"""
    agent = DigestPrepAgent(
        name="period_prep",
        input_key="period_entries",
        output_key="period_digest",
        digest_label="期間",
    )
    assert agent.input_key == "period_entries"
    assert agent.output_key == "period_digest"
    assert agent.digest_label == "期間"
