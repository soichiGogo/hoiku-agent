"""harness.aggregate_by_child の単体テスト（LLM 非依存・高速）。

設計コンテキスト §16：月⇔日の決定的集計は pytest で必須。
"""

from __future__ import annotations

from datetime import date

from hoiku_agent.harness import (
    aggregate_by_child,
    class_plan_history_digest,
    collect_reflections,
    format_class_plan_history_for_prompt,
    format_digest_for_prompt,
    format_reflections_for_prompt,
    prev_month_digest,
)
from hoiku_agent.schemas import (
    AgeBand,
    ClassMonthlyPlan,
    ClassPlanRow,
    DiaryEntry,
    DiaryEvaluation,
    IndividualNote,
    ThreeViewpoint,
)


def _entry(
    day: int,
    child_id: str,
    *,
    child_focus: str = "x",
    self_review: str = "y",
) -> DiaryEntry:
    return DiaryEntry(
        date=date(2026, 6, day),
        age_band=AgeBand.零から二歳,
        weather="晴れ",
        attendance=[],
        practice_record="記録",
        individual_notes=[
            IndividualNote(
                child_id=child_id,
                observed_state=f"{day}日の姿",
                tags=[ThreeViewpoint.身近な人と気持ちが通じ合う],
            )
        ],
        evaluation=DiaryEvaluation(child_focus=child_focus, self_review=self_review),
    )


def test_aggregate_counts_notes_per_child():
    """child_id 別に件数・タグ頻度・観察文が集約される。"""
    digest = aggregate_by_child([_entry(1, "c001"), _entry(2, "c001"), _entry(2, "c002")])
    assert digest["c001"]["note_count"] == 2
    assert digest["c002"]["note_count"] == 1
    assert digest["c001"]["tag_freq"]["身近な人と気持ちが通じ合う"] == 2
    assert len(digest["c001"]["observed_states"]) == 2


def test_prev_month_digest_is_json_serializable():
    """state へ載せる L2 還流の digest は素の dict（Counter でない）で JSON 化できる。"""
    import json

    digest = prev_month_digest([_entry(1, "c001"), _entry(2, "c001")])
    assert digest["c001"]["note_count"] == 2
    # tag_freq は素の dict（Counter は不可）。json.dumps が通る＝state/Memory に載せられる。
    assert isinstance(digest["c001"]["tag_freq"], dict)
    json.dumps(digest, ensure_ascii=False)
    assert digest["c001"]["tag_freq"]["身近な人と気持ちが通じ合う"] == 2


def test_format_digest_lists_facts_without_summarizing():
    """整形テキストは child_id・件数・観察文を列挙する（要約は author の責務＝集計のみ）。"""
    text = format_digest_for_prompt(prev_month_digest([_entry(1, "c001"), _entry(2, "c001")]))
    assert "c001" in text
    assert "1日の姿" in text and "2日の姿" in text


def test_format_digest_empty_degrades():
    """前月データ無し（初月/未提供）でも空 digest で降格メッセージを返す（落ちない）。"""
    text = format_digest_for_prompt(prev_month_digest([]))
    assert "前月の日誌データがありません" in text


# ──────────────── 前月の振り返り（評価・反省）＝クラス月案の L2 還流の一部（決定B） ────────────────


def test_collect_reflections_gathers_nonblank_in_date_order():
    """記入済み（(a)/(b) いずれか非空）の日誌の評価・反省を日付昇順で集める。"""
    entries = [
        _entry(3, "c001", child_focus="3日は水遊びに夢中", self_review=""),
        _entry(1, "c001", child_focus="", self_review="1日は導線を見直したい"),
    ]
    rows = collect_reflections(entries)
    assert [r["date"] for r in rows] == ["2026-06-01", "2026-06-03"]  # 日付昇順
    assert rows[0]["self_review"] == "1日は導線を見直したい"
    assert rows[1]["child_focus"] == "3日は水遊びに夢中"


def test_collect_reflections_skips_blank_both_viewpoints():
    """(a)/(b) とも空（未記入）の日は集めない（プロンプトを膨らませない）。"""
    rows = collect_reflections(
        [
            _entry(1, "c001", child_focus="", self_review=""),  # 未記入＝除外
            _entry(2, "c001", child_focus="姿あり", self_review=""),  # 片方記入＝含む
        ]
    )
    assert len(rows) == 1
    assert rows[0]["date"] == "2026-06-02"


def test_format_reflections_lists_by_date():
    """整形テキストは日付ごとに (a)/(b) を列挙する（要約は author の責務）。"""
    text = format_reflections_for_prompt(
        collect_reflections([_entry(5, "c001", child_focus="姿A", self_review="適否B")])
    )
    assert "2026-06-05" in text and "姿A" in text and "適否B" in text


def test_format_reflections_empty_degrades():
    """記入済みの振り返りが無ければ降格メッセージを返す（落ちない）。"""
    assert "評価・反省がありません" in format_reflections_for_prompt([])


def _class_plan(
    month: str, goal: str, *, aim: str = "", teacher_eval: str = ""
) -> ClassMonthlyPlan:
    grid = [ClassPlanRow(domain="健康", aim=aim)] if aim else []
    return ClassMonthlyPlan(
        month=month,
        age_band=AgeBand.零から二歳,
        monthly_goal=goal,
        prev_month_state="先月の姿",
        grid=grid,
        teacher_evaluation=teacher_eval,
    )


def test_class_plan_history_digest_sorts_by_month_and_keeps_filled_fields():
    """クラス月案の自己履歴＝月昇順（年度跨ぎも辞書順＝時系列）・記入済みのねらい/評価だけ拾う。"""
    history = class_plan_history_digest(
        [
            _class_plan("2026-05", "5月の目標", aim="体を動かす", teacher_eval="評価済み"),
            _class_plan("2026-04", "4月の目標"),
            _class_plan("2027-01", "1月の目標"),  # 年度跨ぎ
        ]
    )
    assert [r["month"] for r in history] == ["2026-04", "2026-05", "2027-01"]
    assert history[1]["aims"] == {"健康": "体を動かす"}
    assert history[1]["teacher_evaluation"] == "評価済み"
    assert history[0]["aims"] == {}  # 空欄行は拾わない（正準化の空行を事実として混ぜない）


def test_format_class_plan_history_lists_facts_without_summarizing():
    """整形は事実列挙のみ（月・目標・ねらい・記入済み評価）。要約は author の責務。"""
    text = format_class_plan_history_for_prompt(
        class_plan_history_digest(
            [_class_plan("2026-05", "5月の目標", aim="体を動かす", teacher_eval="評価済み")]
        ),
        label="これまで",
    )
    assert "【これまでのクラス月案（月順）】" in text
    assert "2026-05" in text and "5月の目標" in text
    assert "健康: 体を動かす" in text
    assert "保育者の評価: 評価済み" in text


def test_format_class_plan_history_empty_degrades():
    """初回（履歴なし）は降格メッセージ（落ちない・偽の中身を出さない）。"""
    assert "作成済みクラス月案がありません" in format_class_plan_history_for_prompt([])
