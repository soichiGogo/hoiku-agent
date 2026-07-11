"""承認済み書類から子ども別の長期記憶を作る（Agent Engine Memory Bank・§9/§13）。

Memory Bank へ渡す内容の決定実体をここに1つ置く。AI の作成セッション全体（プロンプト・レビュー・
ツール応答を含む）ではなく、保育士が確認した**現行版の事実欄**だけを子ども別の fact に変換する。
外部 I/O は ``persist_approved_facts`` に閉じ、fact の抽出は純関数として LLM/GCP 非依存にテストする。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from google.adk.memory.base_memory_service import BaseMemoryService
from google.adk.memory.memory_entry import MemoryEntry
from google.genai import types
from pydantic import ValidationError

from ..schemas import ChildRecord, ClassMonthlyPlan, DiaryEntry, MonthlyPlan, NurseryRecord


@dataclass(frozen=True)
class ApprovedMemoryFact:
    """Memory Bank に渡す、承認版由来の子ども別 fact。"""

    child_id: str
    text: str


def _join_lines(*lines: str) -> str:
    return "\n".join(line.strip() for line in lines if line and line.strip())


def _diary_facts(entry: DiaryEntry) -> list[ApprovedMemoryFact]:
    facts: list[ApprovedMemoryFact] = []
    for note in entry.individual_notes:
        life = note.life_record
        text = _join_lines(
            f"child_id={note.child_id}",
            "書類種別=保育日誌",
            f"記録日={entry.date.isoformat()}",
            f"月齢={note.age_months}" if note.age_months else "",
            f"観察された姿={note.observed_state}" if note.observed_state else "",
            f"食事={life.meal}" if life.meal else "",
            f"睡眠={life.sleep}" if life.sleep else "",
            f"排泄={life.toilet}" if life.toilet else "",
            f"機嫌・体調={life.mood_health}" if life.mood_health else "",
        )
        if note.observed_state or not life.is_blank():
            facts.append(ApprovedMemoryFact(child_id=note.child_id, text=text))
    return facts


def _monthly_facts(entry: MonthlyPlan) -> list[ApprovedMemoryFact]:
    return [
        ApprovedMemoryFact(
            child_id=entry.child_id,
            text=_join_lines(
                f"child_id={entry.child_id}",
                "書類種別=月案",
                f"対象月={entry.month}",
                f"前月までの子どもの姿={entry.prev_child_state}",
                f"評価・反省={entry.evaluation_reflection}",
            ),
        )
    ]


def _class_monthly_facts(entry: ClassMonthlyPlan) -> list[ApprovedMemoryFact]:
    facts: list[ApprovedMemoryFact] = []
    for goal in entry.individual_goals:
        # ねらい・配慮は未来の計画なので、長期記憶の「観察された事実」には混ぜない。
        if not goal.child_state and not goal.evaluation:
            continue
        facts.append(
            ApprovedMemoryFact(
                child_id=goal.child_id,
                text=_join_lines(
                    f"child_id={goal.child_id}",
                    "書類種別=クラス月案（個人目標欄）",
                    f"対象月={entry.month}",
                    f"月齢={goal.age_months}" if goal.age_months else "",
                    f"子どもの姿={goal.child_state}" if goal.child_state else "",
                    f"評価・反省={goal.evaluation}" if goal.evaluation else "",
                ),
            )
        )
    return facts


def _child_record_facts(entry: ChildRecord) -> list[ApprovedMemoryFact]:
    development = " / ".join(note.description for note in entry.development_notes)
    return [
        ApprovedMemoryFact(
            child_id=entry.child_id,
            text=_join_lines(
                f"child_id={entry.child_id}",
                "書類種別=保育経過記録",
                f"対象期間={entry.period}",
                f"発達の経過={development}",
                f"配慮事項・特記={entry.care_notes}" if entry.care_notes else "",
                f"家庭との連携={entry.family_liaison}" if entry.family_liaison else "",
                f"総合所見={entry.overall_note}",
            ),
        )
    ]


def _nursery_record_facts(entry: NurseryRecord) -> list[ApprovedMemoryFact]:
    development = " / ".join(note.description for note in entry.development_notes)
    return [
        ApprovedMemoryFact(
            child_id=entry.child_id,
            text=_join_lines(
                f"child_id={entry.child_id}",
                "書類種別=保育要録",
                f"対象年度={entry.fiscal_year}",
                f"保育の展開と子どもの育ち={development}",
                f"最終年度に至るまでの育ち={entry.growth_until_final}",
                f"特に配慮すべき事項={entry.special_notes}" if entry.special_notes else "",
            ),
        )
    ]


def approved_memory_facts(kind: str, entry: dict) -> list[ApprovedMemoryFact]:
    """承認版から子ども別 fact を決定的に抽出する。

    計画・援助案は将来の意図であって子どもの事実ではないため除外する。クラス月案に個人別の姿・評価が
    無い場合は空（子ども長期記憶へクラス一般論を複製しない）。不正な型は承認前検査の失敗として
    ``ValueError`` に正規化する。
    """
    try:
        if kind == "diary":
            return _diary_facts(DiaryEntry.model_validate(entry))
        if kind == "monthly":
            return _monthly_facts(MonthlyPlan.model_validate(entry))
        if kind == "class_monthly":
            return _class_monthly_facts(ClassMonthlyPlan.model_validate(entry))
        if kind == "child_record":
            return _child_record_facts(ChildRecord.model_validate(entry))
        if kind == "nursery_record":
            return _nursery_record_facts(NurseryRecord.model_validate(entry))
    except (ValidationError, TypeError) as exc:
        raise ValueError(f"承認版をMemory Bank用に検査できません: {exc}") from exc
    raise ValueError(f"未対応の書類種別です: {kind}")


async def persist_approved_facts(
    memory_service: BaseMemoryService,
    *,
    app_name: str,
    user_id: str,
    source_version_id: str,
    facts: Sequence[ApprovedMemoryFact],
) -> None:
    """承認版の fact をMemory Bankへ同期し、生成受付の完了まで待つ。

    ``enable_consolidation`` により既存の子どもの像へ統合する。版IDを本文とmetadataへ含め、再試行時も
    Memory Bank側が同じ出所として統合できるようにする。呼び出し側は成功後にだけ承認・同期済み版を
    DBへ記録する（接続済み環境のfail-closed）。
    """
    if not facts:
        return
    memories = [
        MemoryEntry(
            author="caregiver",
            content=types.Content(
                role="user",
                parts=[
                    types.Part(
                        text=_join_lines(
                            fact.text,
                            f"承認版ID={source_version_id}",
                            "この内容は保育士が確認・承認した記録である。",
                        )
                    )
                ],
            ),
            custom_metadata={"child_id": fact.child_id, "source_version_id": source_version_id},
        )
        for fact in facts
    ]
    await memory_service.add_memory(
        app_name=app_name,
        user_id=user_id,
        memories=memories,
        custom_metadata={
            "enable_consolidation": True,
            "wait_for_completion": True,
            "metadata": {"source_version_id": source_version_id},
        },
    )
