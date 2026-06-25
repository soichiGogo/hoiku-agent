"""月案 harness（validate_monthly_fields / write_monthly_draft / finalize_monthly_document）の単体テスト。

設計コンテキスト §10（月案スキーマ・年齢分岐）/ §16（決定的ロジックは pytest 必須）。LLM 非依存・高速。
日誌（test_schema_check / test_draft / test_finalize）と対称の検査を月案でも担保する。
"""

from __future__ import annotations

import json

from hoiku_agent.harness import (
    finalize_monthly_document,
    validate_monthly_fields,
    write_monthly_draft,
)
from hoiku_agent.schemas import (
    AgeBand,
    FiveDomains,
    MonthlyEducationNote,
    MonthlyPlan,
    ThreeViewpoint,
)


def _plan(
    *,
    age_band: AgeBand = AgeBand.零から二歳,
    education: list | None = None,
    month: str = "2026-07",
    prev_child_state: str = "前月は砂遊びに繰り返し関わった",
    nurturing: str = "睡眠・授乳のリズムを整え情緒の安定を図る",
    monthly_goals: str = "感触遊びを通して感覚的な満足を広げる",
    environment_support: str = "素材を複数用意し落ち着いて関われる場を作る",
    evaluation_reflection: str = "予想したねらいに対し実際の姿はおおむね沿っていた",
) -> MonthlyPlan:
    if education is None:
        education = [
            MonthlyEducationNote(
                aim="身近な素材に触れ感覚を働かせる",
                tags=[ThreeViewpoint.身近なものと関わり感性が育つ],
            )
        ]
    return MonthlyPlan(
        month=month,
        age_band=age_band,
        child_id="架空児A",
        prev_child_state=prev_child_state,
        nurturing=nurturing,
        education=education,
        monthly_goals=monthly_goals,
        environment_support=environment_support,
        evaluation_reflection=evaluation_reflection,
    )


# ──────────────────────── validate_monthly_fields ────────────────────────


def test_valid_monthly_plan_passes():
    assert validate_monthly_fields(_plan()) == []


def test_monthly_0_2_requires_three_viewpoint_tag():
    """0–2 の教育ねらいに3つの視点タグが無ければ違反。"""
    edu = [MonthlyEducationNote(aim="x", tags=[])]
    assert any("3つの視点" in p for p in validate_monthly_fields(_plan(education=edu)))


def test_monthly_3_5_requires_five_domains_tag():
    """3–5 は5領域タグが必須（3つの視点だけでは違反）。"""
    edu = [MonthlyEducationNote(aim="x", tags=[ThreeViewpoint.健やかに伸び伸び育つ])]
    problems = validate_monthly_fields(_plan(age_band=AgeBand.三から五歳, education=edu))
    assert any("5領域" in p for p in problems)


def test_monthly_3_5_with_five_domains_passes():
    edu = [MonthlyEducationNote(aim="言葉のやりとりを楽しむ", tags=[FiveDomains.言葉])]
    assert validate_monthly_fields(_plan(age_band=AgeBand.三から五歳, education=edu)) == []


def test_monthly_empty_education_is_violation():
    assert any("教育のねらい" in p for p in validate_monthly_fields(_plan(education=[])))


def test_monthly_missing_required_fields_are_violations():
    problems = validate_monthly_fields(
        _plan(prev_child_state="  ", nurturing="", monthly_goals="", evaluation_reflection="")
    )
    assert any("前月の子どもの姿" in p for p in problems)
    assert any("養護" in p for p in problems)
    assert any("今月のねらい" in p for p in problems)
    assert any("評価・反省" in p for p in problems)


# ──────────────────────── write_monthly_draft ────────────────────────


def test_write_monthly_draft_renders_sections_and_tags():
    text = write_monthly_draft(_plan())
    for section in ["前月の子どもの姿", "今月のねらい", "養護", "教育", "環境構成", "評価・反省"]:
        assert section in text
    # 枠組みタグを明示出力する（§13 のドメイン作り込み）。
    assert "身近なものと関わり感性が育つ" in text
    assert "2026-07" in text and "架空児A" in text


# ──────────────────────── finalize_monthly_document ────────────────────────


def test_finalize_monthly_success_path():
    """JSON フェンス入りの月案ドラフト→復元・検査通過・整形出力。"""
    draft = "月案の下書きです。\n```json\n" + _plan().model_dump_json() + "\n```"
    result = finalize_monthly_document(draft)
    assert result.parse_error is None
    assert result.problems == []
    assert result.formatted and "前月の子どもの姿" in result.formatted
    assert result.ok


def test_finalize_monthly_parse_error_when_no_json():
    result = finalize_monthly_document("情報不足で作成できませんでした。")
    assert result.parse_error
    assert result.formatted is None
    assert not result.ok


def test_finalize_monthly_surfaces_validation_problems():
    """年齢分岐タグ不足→parse は成功・problems 非空・整形は生成（人が直す）。"""
    plan = _plan(education=[MonthlyEducationNote(aim="x", tags=[FiveDomains.表現])])  # 0–2 に5領域
    draft = "```json\n" + plan.model_dump_json() + "\n```"
    result = finalize_monthly_document(draft)
    assert result.parse_error is None
    assert any("3つの視点" in p for p in result.problems)
    assert result.formatted  # 違反があっても確定下書きは作る
    assert not result.ok


def test_finalize_monthly_dict_roundtrip():
    """model_dump_json 経由でなく素の dict→json でも復元できる（LLM 出力の揺れ耐性）。"""
    payload = json.loads(_plan().model_dump_json())
    draft = "```json\n" + json.dumps(payload, ensure_ascii=False) + "\n```"
    assert finalize_monthly_document(draft).ok
