"""harness：保育要録パイプラインと L4 還流の配線（決定的）。

設計コンテキスト §19（集積階層の最終段 L4＝それまでの保育経過記録を集積して小学校へ引き継ぐ書類）。
保育経過記録（child_record.py＝L3）と対称に、要録の "順序" と "型の保証" をここで決定的に組む。中身の決定
（保育経過記録集積の要約・保育の展開の叙述・入所〜前年度の育ちの叙述・開示前提の表現）は配下の
要録 LlmAgent に委ねる（§6/§19）。

要録パイプライン（doc_type=保育要録 のときルータが選ぶ）:
    record_prep（それまでの保育経過記録を child_id 別に決定的集計＝L4 還流の素データ・月案 L2／保育経過記録 L3 とは
      集計対象が違う＝保育経過記録を集める）→ state["record_digest"]
      → authoring_loop（[nursery_record_author → reviewer → ApprovalGate] を巡回・日誌/月案/保育経過記録と共用）
      → finalize(kind="nursery_record")（NurseryRecord を復元→validate_nursery_record_fields/
        write_nursery_record_draft）
      → [after_agent_callback] persist_visit_to_memory（保育士の明示承認＋型成立のとき書き戻し・§9）

L4 還流の入力（その児のそれまでの保育経過記録＝**全期・年度跨ぎ含む**。依存モデル 2026-07：「対応する
児童の作成済み過去のものすべて」・日誌は足さない）は session state["record_entries"]（ChildRecord の
dict 列）から取る。呼び出し側（scripts/run_youroku.py・web の seed）がアーカイブ
（record_store.list_child_record_entries＝全期を返す）から供給する（未接続はサンプル降格）。
集積階層は 日誌→月案（L2）→保育経過記録（期・L3）→要録（年・L4）＝§19。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, AsyncGenerator

from google.adk.agents import BaseAgent, SequentialAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event, EventActions
from pydantic import ValidationError

from ..agents import build_nursery_record_author_agent
from ..schemas import ChildRecord
from .aggregate import child_record_digest
from .pipeline import (
    FinalizeAgent,
    build_authoring_loop,
    persist_visit_to_memory,
)

if TYPE_CHECKING:
    from google.adk.models import BaseLlm


def _parse_record_entries(raw: object) -> list[ChildRecord]:
    """state["record_entries"]（dict 列）を ChildRecord へ復元する（壊れた要素は黙って飛ばす）。

    L4 還流の集計は "ある分だけ" 行えば足り、1件の不正データで要録作成を止めない（降格の哲学＝月案の
    _parse_prev_entries と同じ）。
    """
    if not isinstance(raw, list):
        return []
    records: list[ChildRecord] = []
    for item in raw:
        try:
            records.append(ChildRecord.model_validate(item))
        except (ValidationError, TypeError):
            continue
    return records


class RecordDigestPrepAgent(BaseAgent):
    """保育経過記録集積の決定的 prep：ChildRecord 群（state[input_key]）を child_id 別に決定的集計する（§19）。

    月案/保育経過記録の DigestPrepAgent が日誌（DiaryEntry）を集計するのに対し、こちらは**保育経過記録
    （ChildRecord）**を集計する（集計対象の型が違うため別 prep）。要録（L4＝record_entries→record_digest・
    既定キー）に加え、保育経過記録の「前回まで」（prev_record_entries→prev_records_digest）・クラス月案の
    「クラス児童のこれまで」（class_record_entries→class_records_digest）でも入出力キー差し替えで共用する
    （依存モデル 2026-07）。集計結果（serializable digest）を state[output_key] に**state-only イベント**
    （content なし）で格納する。author はこの digest を InstructionProvider
    （`agents/instructions.py`＝`format_record_digest_for_prompt`）が prompt 冒頭へ整形注入して読む
    （要約・解釈は author の責務＝§10/§19・ここは集計のみ）。データが無ければ空 digest で素通り（降格）。
    集計の決定的実体は aggregate.py（child_record_digest）＝ここは配線のみ。

    **content を持たせない理由（§12）**：DigestPrepAgent（monthly.py）と同じ＝prep が content 付きイベントを
    先頭に置くと ADK eval の rubric judge が非LLM段を引いて採点不能になる。state-only は eval の
    invocation_events から除外され、先頭 LLM 段＝author が judge の起点になる。
    """

    input_key: str = "record_entries"
    output_key: str = "record_digest"

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        records = _parse_record_entries(ctx.session.state.get(self.input_key))
        digest = child_record_digest(records)
        # content を付けない（state_delta のみ）＝eval の invocation_events に載らず judge を壊さない。
        yield Event(
            invocation_id=ctx.invocation_id,
            author=self.name,
            actions=EventActions(state_delta={self.output_key: digest}),
        )


def build_nursery_record_pipeline(
    author_model: str | BaseLlm | None = None,
    reviewer_model: str | BaseLlm | None = None,
) -> SequentialAgent:
    """保育要録の型を保証するパイプラインを構築する（§19・L4）。

    保育経過記録の build_child_record_pipeline と対称。先頭に RecordDigestPrepAgent（L4 還流の決定的集計＝
    それまでの保育経過記録すべて・入力=record_entries／出力=record_digest）を置き、巡回は
    build_authoring_loop（日誌・月案・保育経過記録と共用。NEEDS_REVISION で nursery_record_author が再作成）、
    finalize は kind="nursery_record"。after_agent_callback も共用（明示承認＋型成立で書き戻し・§9）。
    author_model/reviewer_model は通常 None（実 Gemini）。決定論E2E では FakeLlm を注入する。
    """
    return SequentialAgent(
        name="nursery_record_pipeline",
        sub_agents=[
            RecordDigestPrepAgent(name="record_prep"),
            build_authoring_loop(build_nursery_record_author_agent(author_model), reviewer_model),
            FinalizeAgent(name="finalize", kind="nursery_record"),
        ],
        after_agent_callback=persist_visit_to_memory,
    )
