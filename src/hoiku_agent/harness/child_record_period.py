"""保育経過記録の年度4期（各3か月）を扱う決定的ロジック。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

_QUARTER_MONTHS = ((4, 6), (7, 9), (10, 12), (1, 3))
_PERIOD_RE = re.compile(r"^(\d{4})-(\d{2})[〜~～−―–](\d{4})-(\d{2})$")


@dataclass(frozen=True)
class ChildRecordPeriod:
    """年度4期の1期分。quarter は 1〜4。"""

    fiscal_year: int
    quarter: int
    start_year: int
    start_month: int
    end_year: int
    end_month: int

    @property
    def value(self) -> str:
        return (
            f"{self.start_year:04d}-{self.start_month:02d}"
            f"〜{self.end_year:04d}-{self.end_month:02d}"
        )

    @property
    def label(self) -> str:
        return (
            f"{self.fiscal_year}年度 第{self.quarter}期（{self.start_month}月〜{self.end_month}月）"
        )


def child_record_periods(fiscal_year: int) -> tuple[ChildRecordPeriod, ...]:
    """指定年度の4期（4〜6月、7〜9月、10〜12月、翌1〜3月）を返す。"""
    if fiscal_year < 1:
        raise ValueError(f"年度が不正です: {fiscal_year!r}")
    periods: list[ChildRecordPeriod] = []
    for quarter, (start_month, end_month) in enumerate(_QUARTER_MONTHS, start=1):
        start_year = fiscal_year if start_month >= 4 else fiscal_year + 1
        end_year = fiscal_year if end_month >= 4 else fiscal_year + 1
        periods.append(
            ChildRecordPeriod(
                fiscal_year=fiscal_year,
                quarter=quarter,
                start_year=start_year,
                start_month=start_month,
                end_year=end_year,
                end_month=end_month,
            )
        )
    return tuple(periods)


def fiscal_year_of(day: date) -> int:
    """日付を4月始まりの年度へ変換する。"""
    return day.year if day.month >= 4 else day.year - 1


def child_record_period_for(day: date) -> ChildRecordPeriod:
    """日付を含む保育経過記録の期を返す。"""
    fiscal_year = fiscal_year_of(day)
    for period in child_record_periods(fiscal_year):
        if period.start_month <= day.month <= period.end_month:
            return period
    # 1〜3月は数値上 4〜12月の範囲外なので第4期。
    return child_record_periods(fiscal_year)[3]


def parse_child_record_period(value: str) -> ChildRecordPeriod | None:
    """文字列が年度4期の正しい3か月範囲なら対応する期を返す。

    取込時の区切り表記ゆれは受け入れるが、開始・終了月は年度4期と完全一致させる。
    """
    match = _PERIOD_RE.fullmatch(str(value or "").strip())
    if not match:
        return None
    start_year, start_month, end_year, end_month = (int(part) for part in match.groups())
    fiscal_year = start_year if start_month >= 4 else start_year - 1
    if fiscal_year < 1:
        return None
    for period in child_record_periods(fiscal_year):
        if (
            period.start_year,
            period.start_month,
            period.end_year,
            period.end_month,
        ) == (start_year, start_month, end_year, end_month):
            return period
    return None


def child_record_period_problem(value: str) -> str | None:
    """年度4期・3か月固定に合わなければ利用者向けの違反メッセージを返す。"""
    if parse_child_record_period(value) is not None:
        return None
    return (
        "対象期間（period）は年度4期の3か月単位"
        "（4〜6月／7〜9月／10〜12月／1〜3月）で指定してください: "
        f"{value!r}"
    )


def child_record_period_options(
    reference_date: date, *, past_fiscal_years: int = 5, future_fiscal_years: int = 1
) -> list[dict[str, str | int]]:
    """Web の単一セレクタへ渡す年度・期の選択肢を返す。"""
    current_fiscal_year = fiscal_year_of(reference_date)
    options: list[dict[str, str | int]] = []
    for fiscal_year in range(
        current_fiscal_year - past_fiscal_years,
        current_fiscal_year + future_fiscal_years + 1,
    ):
        for period in child_record_periods(fiscal_year):
            options.append(
                {
                    "value": period.value,
                    "label": period.label,
                    "fiscal_year": period.fiscal_year,
                    "quarter": period.quarter,
                }
            )
    return options
