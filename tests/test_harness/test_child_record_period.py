"""保育経過記録の年度4期・各3か月固定ロジックの単体テスト。"""

from __future__ import annotations

from datetime import date

from hoiku_agent.harness.child_record_period import (
    child_record_period_for,
    child_record_period_options,
    child_record_period_problem,
    child_record_periods,
    parse_child_record_period,
)


def test_child_record_periods_are_four_fixed_three_month_quarters() -> None:
    periods = child_record_periods(2026)
    assert [period.value for period in periods] == [
        "2026-04〜2026-06",
        "2026-07〜2026-09",
        "2026-10〜2026-12",
        "2027-01〜2027-03",
    ]
    assert [period.label for period in periods] == [
        "2026年度 第1期（4月〜6月）",
        "2026年度 第2期（7月〜9月）",
        "2026年度 第3期（10月〜12月）",
        "2026年度 第4期（1月〜3月）",
    ]


def test_child_record_period_for_uses_april_fiscal_year() -> None:
    assert child_record_period_for(date(2026, 4, 1)).value == "2026-04〜2026-06"
    assert child_record_period_for(date(2026, 12, 31)).value == "2026-10〜2026-12"
    assert child_record_period_for(date(2027, 3, 31)).value == "2027-01〜2027-03"


def test_parse_accepts_separator_variation_but_rejects_non_quarter_ranges() -> None:
    parsed = parse_child_record_period("2026-04～2026-06")
    assert parsed is not None and parsed.value == "2026-04〜2026-06"
    for invalid in ("2026-04〜2026-07", "2026-05〜2026-07", "第1期", ""):
        assert parse_child_record_period(invalid) is None
        assert child_record_period_problem(invalid)


def test_period_options_include_current_period_and_are_closed_values() -> None:
    options = child_record_period_options(
        date(2026, 7, 12), past_fiscal_years=0, future_fiscal_years=0
    )
    assert len(options) == 4
    assert options[1] == {
        "value": "2026-07〜2026-09",
        "label": "2026年度 第2期（7月〜9月）",
        "fiscal_year": 2026,
        "quarter": 2,
    }
