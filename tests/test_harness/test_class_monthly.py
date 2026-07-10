"""クラス月案 harness（validate/write/finalize＋grid 正準化）の単体テスト。

設計コンテキスト §10（月案スキーマ）/ §18（園の実様式）/ §16（決定的ロジックは pytest 必須）。
LLM 非依存・高速。個別月案（test_monthly）と対称に、園の実様式のクラス月案の型保証を担保する。
"""

from __future__ import annotations

import json

from hoiku_agent.harness import (
    finalize_class_monthly_document,
    validate_class_monthly_fields,
    write_class_monthly_draft,
)
from hoiku_agent.schemas import (
    AgeBand,
    ClassMonthlyPlan,
    ClassPlanRow,
    GRID_ROWS,
    IndividualGoal,
)


def _full_grid() -> list[ClassPlanRow]:
    return [
        ClassPlanRow(
            category=category,
            domain=domain,
            aim=f"{domain}のねらい",
            environment="環境・構成",
            child_state="子どもの姿",
            support="援助・配慮",
        )
        for category, domain in GRID_ROWS
    ]


def _plan(
    *,
    age_band: AgeBand = AgeBand.零から二歳,
    grid: list[ClassPlanRow] | None = None,
    individual_goals: list[IndividualGoal] | None = None,
    monthly_goal: str = "梅雨期も健康に過ごし、感触遊びを楽しむ",
    prev_month_state: str = "前月は砂遊びに繰り返し関わり感触を楽しんだ",
) -> ClassMonthlyPlan:
    if individual_goals is None and age_band is AgeBand.零から二歳:
        individual_goals = [
            IndividualGoal(
                child_id="架空児A", child_state="歩行が安定", aim_support="探索を保障する"
            )
        ]
    return ClassMonthlyPlan(
        month="2026-07",
        age_band=age_band,
        class_name="ひよこ組",
        monthly_goal=monthly_goal,
        prev_month_state=prev_month_state,
        grid=grid if grid is not None else _full_grid(),
        individual_goals=individual_goals or [],
    )


# ──────────────────────── grid 正準化（model_validator） ────────────────────────


def test_grid_canonicalized_to_seven_rows():
    """AI が行を欠く/並べ替える/区分を取り違えても、正準7行（GRID_ROWS 順）にそろう（型の保証）。"""
    partial = [
        ClassPlanRow(domain="健康", aim="a-health", category="まちがい"),
        ClassPlanRow(domain="生命の保持", aim="a-life"),
        ClassPlanRow(domain="謎領域", aim="drop-me"),  # GRID_ROWS に無い＝落ちる
    ]
    plan = _plan(grid=partial)
    assert [(r.category, r.domain) for r in plan.grid] == GRID_ROWS
    assert plan.grid[0].domain == "生命の保持" and plan.grid[0].aim == "a-life"
    assert (
        plan.grid[2].category == "教育"
        and plan.grid[2].domain == "健康"
        and plan.grid[2].aim == "a-health"
    )
    assert plan.grid[6].domain == "表現" and plan.grid[6].aim == ""  # 欠落領域は空行で補完


# ──────────────────────── validate_class_monthly_fields ────────────────────────


def test_valid_class_monthly_passes():
    assert validate_class_monthly_fields(_plan()) == []


def test_missing_required_top_fields_are_violations():
    problems = validate_class_monthly_fields(_plan(monthly_goal="", prev_month_state="  "))
    assert any("今月の保育目標" in p for p in problems)
    assert any("先月の子どもの姿" in p for p in problems)


def test_grid_missing_aim_is_violation_per_domain():
    """グリッドのねらい未記入は領域ごとに報告される（正準化で7行になった空行も対象）。"""
    grid = [ClassPlanRow(domain="健康", aim="")]  # 他6領域は空行補完＝全7行ねらい未記入
    problems = validate_class_monthly_fields(_plan(grid=grid))
    assert sum(1 for p in problems if "ねらい" in p) == 7
    assert any("表現" in p for p in problems)


def test_month_is_zero_pad_normalized_by_schema():
    """schema の MonthStr が対象月をゼロ詰めに正規化する（"2026-7"→"2026-07"）＝集積の辞書順前提を守る。"""
    assert (
        ClassMonthlyPlan(
            month="2026-7",
            age_band=AgeBand.零から二歳,
            monthly_goal="g",
            prev_month_state="s",
            grid=_full_grid(),
            individual_goals=[IndividualGoal(child_id="架空児A", child_state="s", aim_support="a")],
        ).month
        == "2026-07"
    )


def test_malformed_month_is_violation():
    """解釈不能な月（"2026/07"）は正規化されず、validate が型不成立として可視化する（黙って通さない）。"""
    plan = _plan()
    object.__setattr__(plan, "month", "2026/07")  # 検証を迂回して壊れた月を注入
    problems = validate_class_monthly_fields(plan)
    assert any("YYYY-MM" in p for p in problems)


def test_0_2_requires_individual_goals():
    """0–2 は個人目標が1件以上必須（園フォームに 0–2 だけ個人目標小表がある）。"""
    problems = validate_class_monthly_fields(_plan(individual_goals=[]))
    assert any("個人目標" in p for p in problems)


def test_0_2_individual_goal_requires_state_and_aim():
    goal = IndividualGoal(child_id="架空児A", child_state="", aim_support="")
    problems = validate_class_monthly_fields(_plan(individual_goals=[goal]))
    assert any("子どもの姿" in p for p in problems)
    assert any("ねらい・配慮" in p for p in problems)


def test_3_5_needs_no_individual_goals():
    """3–5 は個人目標が無くても充足（様式に個人目標小表が無い＝§18）。"""
    assert (
        validate_class_monthly_fields(_plan(age_band=AgeBand.三から五歳, individual_goals=[])) == []
    )


# ──────────────────────── write_class_monthly_draft ────────────────────────


def test_write_class_monthly_renders_form_sections():
    text = write_class_monthly_draft(_plan())
    for section in [
        "月間指導計画",
        "今月の保育目標",
        "先月の子どもの姿",
        "指導計画（区分×領域）",
        "養護",
        "教育",
        "個人目標",
    ]:
        assert section in text
    assert "2026-07" in text and "ひよこ組" in text
    # 0–2 は 0〜2歳児のタイトル
    assert "0〜2歳児" in text


def test_write_class_monthly_3_5_omits_individual_goals():
    text = write_class_monthly_draft(_plan(age_band=AgeBand.三から五歳, individual_goals=[]))
    assert "3歳以上児" in text
    assert "個人目標" not in text  # 3–5 は個人目標を出さない


# ──────────────────────── finalize_class_monthly_document ────────────────────────


def test_finalize_class_monthly_success_path():
    draft = "クラス月案の下書きです。\n```json\n" + _plan().model_dump_json() + "\n```"
    result = finalize_class_monthly_document(draft)
    assert result.parse_error is None
    assert result.problems == []
    assert result.formatted and "月間指導計画" in result.formatted
    assert result.ok


def test_finalize_class_monthly_parse_error_when_no_json():
    result = finalize_class_monthly_document("情報不足で作成できませんでした。")
    assert result.parse_error
    assert not result.ok


def test_finalize_class_monthly_dict_roundtrip():
    payload = json.loads(_plan().model_dump_json())
    draft = "```json\n" + json.dumps(payload, ensure_ascii=False) + "\n```"
    assert finalize_class_monthly_document(draft).ok
