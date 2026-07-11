"""harness：月案パイプラインと L2 還流の配線（決定的）。

設計コンテキスト §3「月案は日誌の集積に乗せる」/ §4「L2 月次PDCA」/ §10「月⇄日の集積連携」。
日誌（pipeline.py）と対称に、月案の "順序" と "型の保証" をここで決定的に組む。中身の決定（前月集積の
要約・ねらいへの変換）は配下の月案 LlmAgent に委ねる（§6/§10）。

月案パイプライン（doc_type=月案 のときルータが選ぶ）:
    monthly_prep（前月日誌を child_id 別に決定的集計＝L2 還流の素データ）→ state["prev_month_digest"]
      → authoring_loop（[monthly_author → reviewer → ApprovalGate] を巡回・日誌と共用。NEEDS_REVISION で
        monthly_author が指摘点を再作成）→ state["draft"]/["review"]
      → finalize(kind="monthly")（MonthlyPlan を復元→validate_monthly_fields/write_monthly_draft）
      → 承認後のMemory Bank書き戻しは web `/api/records/approve`（§9）

L2 還流の入力（前月日誌）は session state["prev_month_entries"]（DiaryEntry の dict 列）から取る。
v0 では呼び出し側（scripts/run_monthly.py・月案デモの seeding）が前月日誌を seed する。将来は
search_past_documents / アーカイブから供給する（§10「保存先＝state／必要なら Memory Bank」）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, AsyncGenerator

from google.adk.agents import BaseAgent, SequentialAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event, EventActions
from pydantic import ValidationError

from ..agents import build_monthly_author_agent
from ..schemas import DiaryEntry
from .aggregate import collect_reflections, prev_month_digest
from .record_store import covered_until, covered_until_by_child
from .pipeline import (
    FinalizeAgent,
    build_authoring_loop,
)

if TYPE_CHECKING:
    from google.adk.models import BaseLlm


def _parse_prev_entries(raw: object) -> list[DiaryEntry]:
    """state["prev_month_entries"]（dict 列）を DiaryEntry へ復元する（壊れた要素は黙って飛ばす）。

    L2 還流の集計は "ある分だけ" 行えば足り、1件の不正データで月案作成を止めない（降格の哲学）。
    """
    if not isinstance(raw, list):
        return []
    entries: list[DiaryEntry] = []
    for item in raw:
        try:
            entries.append(DiaryEntry.model_validate(item))
        except (ValidationError, TypeError):
            continue
    return entries


class DigestPrepAgent(BaseAgent):
    """集積還流の決定的 prep：日誌群（state[input_key]）を child_id 別に決定的集計する（§10/§19）。

    集計結果（serializable digest）を state[output_key] に**state-only イベント**（content なし）で
    格納する。author はこの digest を InstructionProvider（`agents/instructions.py`）が prompt 冒頭へ
    整形注入して読む（要約・解釈は author の責務＝§10・ここは集計のみ）。データが無ければ空 digest で
    素通り（降格）。月案（L2 還流＝前月日誌・既定キー）と保育経過記録（L3 還流＝期間日誌）で共用する
    （集計の決定的実体は aggregate.py に1つ・ここは配線のみ）。旧名 MonthlyPrepAgent を一般化した。

    `reflections_key` を与えると（クラス月案のみ）、日誌の評価・反省を日次のクラス全体所見として
    `collect_reflections` で日付順に集め、同じ state-only イベントで state[reflections_key] にも載せる
    （個別月案・保育経過記録は None＝従来どおり digest のみ・挙動不変・§10 決定B）。

    `uncovered_by_key` を与えると（クラス月案のみ・依存モデル 2026-07）、state[uncovered_by_key] の
    保育経過記録群から**児童別の「反映済み最終日」**（`record_store.covered_until_by_child`）を求め、
    child_id 別集積（digest）では各児にとって未反映の note だけを残す（記録が遅れている児＝途中入園児等は
    境界が無い＝全 note を残す）。クラス一律 max 境界だと記録が進んだ児に引きずられて遅れている児の日誌が
    丸ごと落ちる欠陥の是正（安全側＝情報を落とさない）。一方、日次の評価・反省（`reflections_key`）は
    child_id 別でなくクラス全体の所見なので、従来どおりクラス一律の `covered_until`（max）で日を絞る
    （seed 側の合成 `class_monthly_seed_inputs` は両者を賄う superset を state に渡す）。

    **content を持たせない理由（§12）**：ADK eval の rubric judge は invocation の先頭イベント著者の
    developer instructions を引く（LLM 段のみ登録）。prep が content 付きイベントを先頭に置くと judge が
    非LLM段を引いて採点不能になる。state-only イベントは eval の invocation_events から除外されるため
    （content の無いイベントは集計対象外）、先頭の LLM 段＝author が judge の起点になり採点が通る。
    """

    input_key: str = "prev_month_entries"
    output_key: str = "prev_month_digest"
    reflections_key: str | None = None  # 設定時のみ日誌の評価・反省も集める（クラス月案・決定B）
    uncovered_by_key: str | None = None  # 設定時のみ経過記録に未反映の日誌へ限定（クラス月案）

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        entries = _parse_prev_entries(ctx.session.state.get(self.input_key))
        covered_by_child: dict | None = None
        reflection_entries = entries
        if self.uncovered_by_key:
            records = ctx.session.state.get(self.uncovered_by_key)
            records = records if isinstance(records, list) else []
            # digest＝児童別境界（各児の未反映 note だけ残す）／評価・反省＝クラス一律 max 境界で日を絞る。
            covered_by_child = covered_until_by_child(records)
            class_boundary = covered_until(
                str(r.get("period") or "") for r in records if isinstance(r, dict)
            )
            if class_boundary is not None:
                reflection_entries = [e for e in entries if e.date > class_boundary]
        state_delta: dict = {self.output_key: prev_month_digest(entries, covered_by_child)}
        if self.reflections_key:
            state_delta[self.reflections_key] = collect_reflections(reflection_entries)
        # content を付けない（state_delta のみ）＝eval の invocation_events に載らず judge を壊さない。
        yield Event(
            invocation_id=ctx.invocation_id,
            author=self.name,
            actions=EventActions(state_delta=state_delta),
        )


def build_monthly_pipeline(
    author_model: str | BaseLlm | None = None,
    reviewer_model: str | BaseLlm | None = None,
) -> SequentialAgent:
    """個別月案の型を保証する月案パイプラインを構築する（§3/§4/§10）。

    共用機構（authoring_loop→finalize）に対称。先頭に DigestPrepAgent（L2 還流の決定的集計＝state-only）を
    置き、巡回は build_authoring_loop（[monthly_author → reviewer → ApprovalGate]・日誌と共用。
    NEEDS_REVISION で monthly_author が再作成）、finalize は kind="monthly"。文書作成指針と前月集積は
    monthly_author/reviewer の InstructionProvider（`agents/instructions.py`）が prompt 冒頭へ注入する（§5）。
    承認後の書き戻しはWeb承認APIへ一本化する。author_model/reviewer_model は
    通常 None（実 Gemini）。決定論E2E では FakeLlm を注入する。
    """
    return SequentialAgent(
        name="monthly_plan_pipeline",
        sub_agents=[
            DigestPrepAgent(name="monthly_prep"),
            build_authoring_loop(build_monthly_author_agent(author_model), reviewer_model),
            FinalizeAgent(name="finalize", kind="monthly"),
        ],
    )
