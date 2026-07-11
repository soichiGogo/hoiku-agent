"""harness：クラス月案パイプラインと集積還流の配線（決定的）。

設計コンテキスト §3「月案は日誌の集積に乗せる」/ §10（集積連携）/ §18（園の実様式）/
依存モデル（2026-07 確定）。個別月案（monthly.py）と対称に、**園の実様式（月間指導計画・クラス単位）**の
型を保証する。個別月案が1人の子の月次計画なのに対し、クラス月案はクラス全体の月次計画。

クラス月案の入力（依存モデル 2026-07）は3系統：
① クラス児童の作成済み保育経過記録すべて（全期・年度跨ぎ含む）＝これまでの育ちの土台
② それまでの作成済みクラス月案すべて（全期）＝計画の連続性（ねらいの発展・月末評価の反映）
③ **保育経過記録にまだ反映されていない当該クラスの日誌**（＝**児童別**に、各児の経過記録に未反映の
   note だけ。記録が進んだ児は①で見るため重複させないが、記録が遅れている児〔途中入園児等〕の note は
   クラス一律 max 境界で落とさず残す＝安全側）＋その評価・反省（決定B・日次のクラス所見なので従来どおり）

クラス月案パイプライン（doc_type=クラス月案 のときルータが選ぶ）:
    class_record_prep（①を child_id 別に決定的集計・RecordDigestPrepAgent を要録と共用・
      入力=class_record_entries／出力=class_records_digest）
    class_plan_prep（②を月順の履歴に決定的集計・入力=past_class_plans／出力=class_plan_digest）
    class_diary_prep（③を child_id 別に決定的集計・DigestPrepAgent を個別月案と共用・
      入力=class_diary_entries／出力=class_diary_digest・`uncovered_by_key` で①から**児童別境界**を求め
      各児の未反映 note に限定〔`covered_until_by_child`〕・評価・反省は reflections_key=class_diary_reflections
      にクラス一律 max 境界で別チャネル集約＝決定B）
      → authoring_loop（[class_monthly_author → reviewer → ApprovalGate] を巡回・共用）
      → finalize(kind="class_monthly")（ClassMonthlyPlan を復元→validate/write）
      → 承認後のMemory Bank書き戻しは web `/api/records/approve`（§9）

呼び出し側（scripts/run_class_monthly.py・web の seed）は `record_store.class_monthly_seed_inputs` で
3入力を合成して seed する（③の探索は当該年度内＝`fiscal_year_start`で前年度コホートを混ぜず、児童別境界
`covered_until_by_child` で未反映 note を含む日誌だけ残す。note 単位の実際の絞り込みは prep/aggregate が
担い決定実体は1つ）。未接続・該当なしは空＝各 digest が降格メッセージへ。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, AsyncGenerator

from google.adk.agents import BaseAgent, SequentialAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event, EventActions
from pydantic import ValidationError

from ..agents import build_class_monthly_author_agent
from ..schemas import ClassMonthlyPlan
from .aggregate import class_plan_history_digest
from .monthly import DigestPrepAgent
from .pipeline import (
    FinalizeAgent,
    build_authoring_loop,
)
from .youroku import RecordDigestPrepAgent

if TYPE_CHECKING:
    from google.adk.models import BaseLlm


def _parse_class_plans(raw: object) -> list[ClassMonthlyPlan]:
    """state["past_class_plans"]（dict 列）を ClassMonthlyPlan へ復元する（壊れた要素は黙って飛ばす）。

    自己履歴の集計は "ある分だけ" 行えば足り、1件の不正データでクラス月案作成を止めない
    （降格の哲学＝月案の _parse_prev_entries と同じ）。
    """
    if not isinstance(raw, list):
        return []
    plans: list[ClassMonthlyPlan] = []
    for item in raw:
        try:
            plans.append(ClassMonthlyPlan.model_validate(item))
        except (ValidationError, TypeError):
            continue
    return plans


class ClassPlanPrepAgent(BaseAgent):
    """クラス月案の自己履歴の決定的 prep：それまでのクラス月案（state[input_key]）を月順に集計する。

    集計結果（serializable な月順履歴）を state[output_key] に**state-only イベント**（content なし・
    §12＝eval judge を壊さない）で格納する。author はこの履歴を InstructionProvider
    （`agents/instructions.py`＝`format_class_plan_history_for_prompt`）が prompt 冒頭へ整形注入して読む
    （計画の連続性の解釈は author の責務・ここは集計のみ）。データが無ければ空履歴で素通り（降格）。
    集計の決定的実体は aggregate.py（class_plan_history_digest）＝ここは配線のみ。
    """

    input_key: str = "past_class_plans"
    output_key: str = "class_plan_digest"

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        plans = _parse_class_plans(ctx.session.state.get(self.input_key))
        history = class_plan_history_digest(plans)
        # content を付けない（state_delta のみ）＝eval の invocation_events に載らず judge を壊さない。
        yield Event(
            invocation_id=ctx.invocation_id,
            author=self.name,
            actions=EventActions(state_delta={self.output_key: history}),
        )


def build_class_monthly_pipeline(
    author_model: str | BaseLlm | None = None,
    reviewer_model: str | BaseLlm | None = None,
) -> SequentialAgent:
    """クラス月案（園の実様式）の型を保証するパイプラインを構築する（§18・依存モデル 2026-07）。

    先頭に3つの決定的 prep（いずれも state-only）を置く：クラス児童の保育経過記録集積
    （RecordDigestPrepAgent 共用）／それまでのクラス月案の履歴（ClassPlanPrepAgent）／経過記録に
    未反映の期間の日誌集積＋評価・反省（DigestPrepAgent 共用・uncovered_by_key で境界限定）。
    巡回は build_authoring_loop（共用。NEEDS_REVISION で class_monthly_author が再作成）、finalize は
    kind="class_monthly"。文書作成指針（scope=月案を流用）と各集積は class_monthly_author/reviewer の
    InstructionProvider（`agents/instructions.py`）が prompt 冒頭へ注入する（§5）。承認後の書き戻しは
    Web承認APIへ一本化する。author_model/reviewer_model は通常 None（実 Gemini）。
    決定論E2E では FakeLlm を注入する。
    """
    return SequentialAgent(
        name="class_monthly_pipeline",
        sub_agents=[
            # ① クラス児童の保育経過記録すべて（全期）＝これまでの育ち。
            RecordDigestPrepAgent(
                name="class_record_prep",
                input_key="class_record_entries",
                output_key="class_records_digest",
            ),
            # ② それまでのクラス月案すべて＝計画の連続性。
            ClassPlanPrepAgent(name="class_plan_prep"),
            # ③ 経過記録に未反映の期間の日誌（①の境界より後に限定）＋評価・反省（決定B）。
            DigestPrepAgent(
                name="class_diary_prep",
                input_key="class_diary_entries",
                output_key="class_diary_digest",
                reflections_key="class_diary_reflections",
                uncovered_by_key="class_record_entries",
            ),
            build_authoring_loop(build_class_monthly_author_agent(author_model), reviewer_model),
            FinalizeAgent(name="finalize", kind="class_monthly"),
        ],
    )
