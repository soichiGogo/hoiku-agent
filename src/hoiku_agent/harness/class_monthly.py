"""harness：クラス月案パイプラインと L2 還流の配線（決定的）。

設計コンテキスト §3「月案は日誌の集積に乗せる」/ §10（月⇄日の集積連携）/ §18（園の実様式）。
個別月案（monthly.py）と対称に、**園の実様式（月間指導計画・クラス単位）**の型を保証する。個別月案が
1人の子の月次計画なのに対し、クラス月案はクラス全体の月次計画で、前月日誌の集積（L2 還流・全登場児）を
「先月の子どもの姿」と区分×領域グリッド・0–2 の個人目標へ流す。

クラス月案パイプライン（doc_type=クラス月案 のときルータが選ぶ）:
    class_month_prep（前月日誌を child_id 別に決定的集計＝L2 還流・DigestPrepAgent を個別月案と共用・
      入力=prev_month_entries／出力=prev_month_digest）→ state["prev_month_digest"]
      → authoring_loop（[class_monthly_author → reviewer → ApprovalGate] を巡回・日誌/月案と共用）
      → finalize(kind="class_monthly")（ClassMonthlyPlan を復元→validate/write）
      → [after_agent_callback] persist_visit_to_memory（明示承認＋型成立のとき書き戻し・§9）

L2 還流の入力（前月日誌）は個別月案と同じ state["prev_month_entries"]（DiaryEntry の dict 列）から取る。
呼び出し側（scripts/run_class_monthly.py・web の seed）が前月の当該年齢帯の日誌を seed する。集積は
child_id 別なので、digest はクラス全登場児ぶんになる（個人目標＝0–2 はその全員分を author が生成）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from google.adk.agents import SequentialAgent

from ..agents import build_class_monthly_author_agent
from .monthly import DigestPrepAgent
from .pipeline import (
    FinalizeAgent,
    build_authoring_loop,
    persist_visit_to_memory,
)

if TYPE_CHECKING:
    from google.adk.models import BaseLlm


def build_class_monthly_pipeline(
    author_model: str | BaseLlm | None = None,
    reviewer_model: str | BaseLlm | None = None,
) -> SequentialAgent:
    """クラス月案（園の実様式）の型を保証するパイプラインを構築する（§18）。

    個別月案の build_monthly_pipeline と対称。先頭に DigestPrepAgent（L2 還流の決定的集計・state-only・
    入力=prev_month_entries／出力=prev_month_digest＝個別月案と同じ既定キー）を置き、巡回は
    build_authoring_loop（日誌・月案と共用。NEEDS_REVISION で class_monthly_author が再作成）、finalize は
    kind="class_monthly"。文書作成指針（scope=月案を流用）と前月集積は class_monthly_author/reviewer の
    InstructionProvider（`agents/instructions.py`）が prompt 冒頭へ注入する（§5）。after_agent_callback も
    共用（明示承認＋型成立で書き戻し・§9）。author_model/reviewer_model は通常 None（実 Gemini）。
    決定論E2E では FakeLlm を注入する。
    """
    return SequentialAgent(
        name="class_monthly_pipeline",
        sub_agents=[
            # reflections_key＝前月日誌の評価・反省も日付順に集める（クラス月案のみ＝§10 決定B）。
            DigestPrepAgent(name="class_month_prep", reflections_key="prev_month_reflections"),
            build_authoring_loop(build_class_monthly_author_agent(author_model), reviewer_model),
            FinalizeAgent(name="finalize", kind="class_monthly"),
        ],
        after_agent_callback=persist_visit_to_memory,
    )
