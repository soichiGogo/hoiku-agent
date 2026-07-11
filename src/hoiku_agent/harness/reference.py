"""参照候補を決定的に集計する harness 実体。"""

from __future__ import annotations

from pydantic import ValidationError

from ..schemas import ChildRecord, ClassMonthlyPlan, DiaryEntry, ReferenceSource
from .aggregate import (
    child_record_digest,
    class_plan_history_digest,
    collect_reflections,
    format_class_plan_history_for_prompt,
    format_digest_for_prompt,
    format_record_digest_for_prompt,
    format_reflections_for_prompt,
    prev_month_digest,
)
from .record_store import covered_until, covered_until_by_child

_STATE_KEYS: dict[ReferenceSource, tuple[str, ...]] = {
    ReferenceSource.prev_month_diaries: ("prev_month_entries",),
    ReferenceSource.period_diary: ("period_entries",),
    ReferenceSource.prev_child_records: ("prev_record_entries", "record_entries"),
    ReferenceSource.class_child_records: ("class_record_entries",),
    ReferenceSource.past_class_plans: ("past_class_plans",),
    ReferenceSource.uncovered_class_diaries: ("class_diary_entries",),
}


def _rows(state: dict, source: ReferenceSource) -> list:
    for key in _STATE_KEYS[source]:
        value = state.get(key)
        if isinstance(value, list):
            return value
    return []


def _parse(rows: list, model) -> list:
    parsed = []
    for row in rows:
        try:
            parsed.append(model.model_validate(row))
        except (ValidationError, TypeError):
            continue
    return parsed


def fetch_reference_from_state(state: dict, source: ReferenceSource | str) -> dict:
    """source に対応する seed 候補をその場で digest 化し、manifest を state に記録する。

    ADK の FunctionTool はツール引数を素の str で渡すため、入口で ReferenceSource へ
    決定的に coerce する（str Enum ゆえ dict 引き・比較は素通りし `.value` だけが落ちる罠）。
    未知の値は例外にせず正直に降格（有効な語彙を返して agent が選び直せるようにする）。
    """
    try:
        source = ReferenceSource(source)
    except ValueError:
        valid = "、".join(member.value for member in ReferenceSource)
        return {
            "source": str(source),
            "count": 0,
            "empty": True,
            "content": f"未知の参照種別です。有効な参照種別: {valid}",
        }
    rows = _rows(state, source)
    if source in {ReferenceSource.prev_month_diaries, ReferenceSource.period_diary}:
        entries = _parse(rows, DiaryEntry)
        label = "前月" if source == ReferenceSource.prev_month_diaries else "期間"
        content = format_digest_for_prompt(prev_month_digest(entries), label)
        count = len(entries)
    elif source == ReferenceSource.uncovered_class_diaries:
        entries = _parse(rows, DiaryEntry)
        records = _rows(state, ReferenceSource.class_child_records)
        by_child = covered_until_by_child(records)
        digest = prev_month_digest(entries, by_child)
        boundary = covered_until(
            str(row.get("period") or "") for row in records if isinstance(row, dict)
        )
        reflection_entries = [e for e in entries if boundary is None or e.date > boundary]
        content = "\n\n".join(
            [
                format_digest_for_prompt(digest, "経過記録に未反映の期間"),
                format_reflections_for_prompt(
                    collect_reflections(reflection_entries), "経過記録に未反映の期間"
                ),
            ]
        )
        count = len(entries)
    elif source == ReferenceSource.past_class_plans:
        plans = _parse(rows, ClassMonthlyPlan)
        content = format_class_plan_history_for_prompt(class_plan_history_digest(plans))
        count = len(plans)
    else:
        records = _parse(rows, ChildRecord)
        content = format_record_digest_for_prompt(child_record_digest(records))
        count = len(records)

    manifest = list(state.get("reference_manifest") or [])
    manifest.append({"source": source.value, "count": count, "empty": count == 0})
    state["reference_manifest"] = manifest
    return {"source": source.value, "count": count, "empty": count == 0, "content": content}
