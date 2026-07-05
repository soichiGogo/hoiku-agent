"""harness：児童票パイプラインと L3 還流の配線（決定的）。

設計コンテキスト §19（ヒアリング反映 2026-07：児童票＝期ごとの保育経過記録・L3 集積）。
月案（monthly.py＝L2 還流）と対称に、児童票の "順序" と "型の保証" をここで決定的に組む。
中身の決定（期間集積の要約・領域別の叙述・開示前提の表現）は配下の児童票 LlmAgent に委ねる（§6/§19）。

児童票パイプライン（doc_type=児童票 のときルータが選ぶ）:
    period_prep（期間中の日誌を child_id 別に決定的集計＝L3 還流の素データ・DigestPrepAgent を
      月案と共用）→ state["period_digest"]
      → authoring_loop（[child_record_author → reviewer → ApprovalGate] を巡回・日誌/月案と共用）
      → finalize(kind="child_record")（ChildRecord を復元→validate_child_record_fields/
        write_child_record_draft）
      → [after_agent_callback] persist_visit_to_memory（保育士の明示承認＋型成立のとき書き戻し・§9）

L3 還流の入力（期間中の日誌）は session state["period_entries"]（DiaryEntry の dict 列）から取る。
期の区切り（月次/3期/4期制）は園差＝呼び出し側（scripts/run_child_record.py・web の seed）が
期間分の日誌を seed して表現する（期制の設定化は残課題＝§18 と同じ現場依存）。
集積階層は 日誌→月案（L2）→児童票（期・L3）→要録（将来）＝§19。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from google.adk.agents import SequentialAgent

from ..agents import build_child_record_author_agent
from .monthly import DigestPrepAgent
from .pipeline import (
    FinalizeAgent,
    build_authoring_loop,
    persist_visit_to_memory,
)

if TYPE_CHECKING:
    from google.adk.models import BaseLlm


def build_child_record_pipeline(
    author_model: str | BaseLlm | None = None,
    reviewer_model: str | BaseLlm | None = None,
) -> SequentialAgent:
    """児童票の型を保証するパイプラインを構築する（§19）。

    月案の build_monthly_pipeline と対称。先頭に DigestPrepAgent（L3 還流の決定的集計・state-only・
    入力=period_entries／出力=period_digest）を置き、巡回は build_authoring_loop（日誌・月案と共用。
    NEEDS_REVISION で child_record_author が再作成）、finalize は kind="child_record"。文書作成指針と
    期間集積は child_record_author/reviewer の InstructionProvider（`agents/instructions.py`）が prompt
    冒頭へ注入する（§5）。after_agent_callback も共用（明示承認＋型成立で書き戻し・§9）。
    author_model/reviewer_model は通常 None（実 Gemini）。決定論E2E では FakeLlm を注入する。
    """
    return SequentialAgent(
        name="child_record_pipeline",
        sub_agents=[
            DigestPrepAgent(
                name="period_prep",
                input_key="period_entries",
                output_key="period_digest",
            ),
            build_authoring_loop(build_child_record_author_agent(author_model), reviewer_model),
            FinalizeAgent(name="finalize", kind="child_record"),
        ],
        after_agent_callback=persist_visit_to_memory,
    )
