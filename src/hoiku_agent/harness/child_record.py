"""harness：保育経過記録パイプラインと L3 還流の配線（決定的）。

設計コンテキスト §19（ヒアリング反映 2026-07：保育経過記録（期ごと）・L3 集積）。
月案（monthly.py＝L2 還流）と対称に、保育経過記録の "順序" と "型の保証" をここで決定的に組む。
中身の決定（期間集積の要約・領域別の叙述・開示前提の表現）は配下の保育経過記録 LlmAgent に委ねる（§6/§19）。

保育経過記録パイプライン（doc_type=保育経過記録 のときルータが選ぶ）:
    period_prep（期間中の日誌を child_id 別に決定的集計＝L3 還流の素データ・DigestPrepAgent を
      月案と共用）→ state["period_digest"]
    prev_record_prep（**前回までの保育経過記録**＝その児の作成済み過去の記録すべてを child_id 別に
      決定的集計・RecordDigestPrepAgent を要録と共用＝依存モデル 2026-07）→ state["prev_records_digest"]
      → authoring_loop（[child_record_author → reviewer → ApprovalGate] を巡回・日誌/月案と共用）
      → finalize(kind="child_record")（ChildRecord を復元→validate_child_record_fields/
        write_child_record_draft）
      → 承認後のMemory Bank書き戻しは web `/api/records/approve`（§9）

入力は session state から取る（依存モデル 2026-07＝①該当期間の日誌＋②前回までの保育経過記録）:
- state["period_entries"]（DiaryEntry の dict 列）＝該当期間の日誌。
- state["prev_record_entries"]（ChildRecord の dict 列）＝その児の作成済み過去の保育経過記録すべて
  （**全期・年度跨ぎ含む**・作成対象の期は除く＝`record_store.list_child_record_entries(exclude_period=…)`）。
期の区切り（月次/3期/4期制）は園差＝呼び出し側（scripts/run_child_record.py・web の seed）が
期間分の日誌を seed して表現する（期制の設定化は残課題＝§18 と同じ現場依存）。
集積階層は 日誌→月案（L2）→保育経過記録（期・L3）→要録（年・L4）＝§19。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from google.adk.agents import SequentialAgent

from ..agents import build_child_record_author_agent
from .monthly import DigestPrepAgent
from .pipeline import (
    FinalizeAgent,
    build_authoring_loop,
)
from .youroku import RecordDigestPrepAgent

if TYPE_CHECKING:
    from google.adk.models import BaseLlm


def build_child_record_pipeline(
    author_model: str | BaseLlm | None = None,
    reviewer_model: str | BaseLlm | None = None,
) -> SequentialAgent:
    """保育経過記録の型を保証するパイプラインを構築する（§19）。

    月案の build_monthly_pipeline と対称。先頭に DigestPrepAgent（L3 還流の決定的集計・state-only・
    入力=period_entries／出力=period_digest）と RecordDigestPrepAgent（前回までの保育経過記録の集計・
    入力=prev_record_entries／出力=prev_records_digest＝前期からの育ちの連続性の素・依存モデル 2026-07）を
    置き、巡回は build_authoring_loop（日誌・月案と共用。NEEDS_REVISION で child_record_author が再作成）、
    finalize は kind="child_record"。文書作成指針と両集積は child_record_author/reviewer の
    InstructionProvider（`agents/instructions.py`）が prompt 冒頭へ注入する（§5）。承認後の書き戻しは
    Web承認APIへ一本化する。author_model/reviewer_model は通常 None（実 Gemini）。
    決定論E2E では FakeLlm を注入する。
    """
    return SequentialAgent(
        name="child_record_pipeline",
        sub_agents=[
            DigestPrepAgent(
                name="period_prep",
                input_key="period_entries",
                output_key="period_digest",
            ),
            RecordDigestPrepAgent(
                name="prev_record_prep",
                input_key="prev_record_entries",
                output_key="prev_records_digest",
            ),
            build_authoring_loop(build_child_record_author_agent(author_model), reviewer_model),
            FinalizeAgent(name="finalize", kind="child_record"),
        ],
    )
