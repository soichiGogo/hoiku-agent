"""harness：月案パイプラインと L2 還流の配線（決定的）。

設計コンテキスト §3「月案は日誌の集積に乗せる」/ §4「L2 月次PDCA」/ §10「月⇄日の集積連携」。
日誌（pipeline.py）と対称に、月案の "順序" と "型の保証" をここで決定的に組む。中身の決定（前月集積の
要約・ねらいへの変換）は配下の月案 LlmAgent に委ねる（§6/§10）。

月案パイプライン（doc_type=月案 のときルータが選ぶ）:
    monthly_prep（前月日誌を child_id 別に決定的集計＝L2 還流の素データ）→ state["prev_month_digest"]
      → monthly_author（前月集積＋子の像から「前月の姿／評価反省」を要約・ねらいへ変換）→ state["draft"]
      → review_loop（reviewer→ApprovalGate・日誌と共用）
      → finalize(kind="monthly")（MonthlyPlan を復元→validate_monthly_fields/write_monthly_draft）
      → [after_agent_callback] persist_visit_to_memory（型成立の確定時のみ子の像へ書き戻し・§9）

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
from .aggregate import format_digest_for_prompt, prev_month_digest
from .pipeline import (
    FinalizeAgent,
    _model_content,
    build_review_loop,
    persist_visit_to_memory,
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


class MonthlyPrepAgent(BaseAgent):
    """L2 還流：前月日誌（state["prev_month_entries"]）を child_id 別に決定的集計する（§10）。

    集計結果（serializable digest）を state["prev_month_digest"] に格納し、人間可読テキストを
    イベントとして提示する（後段の月案 author が直前メッセージとして読み、要約に使う）。要約・
    解釈は author の責務（§10）＝ここでは集計のみ。前月データが無ければ空 digest で素通り（降格）。
    """

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        entries = _parse_prev_entries(ctx.session.state.get("prev_month_entries"))
        digest = prev_month_digest(entries)
        yield Event(
            author=self.name,
            content=_model_content(format_digest_for_prompt(digest)),
            actions=EventActions(state_delta={"prev_month_digest": digest}),
        )


def build_monthly_pipeline(
    author_model: str | BaseLlm | None = None,
    reviewer_model: str | BaseLlm | None = None,
) -> SequentialAgent:
    """個別月案の型を保証する月案パイプラインを構築する（§3/§4/§10）。

    日誌の build_document_pipeline と対称。先頭に MonthlyPrepAgent（L2 還流の決定的集計）を置き、
    finalize は kind="monthly"。after_agent_callback は日誌と共用（型成立の確定時のみ書き戻し・§9）。
    author_model/reviewer_model は通常 None（実 Gemini）。決定論E2E では FakeLlm を注入する。
    """
    return SequentialAgent(
        name="monthly_plan_pipeline",
        sub_agents=[
            MonthlyPrepAgent(name="monthly_prep"),
            build_monthly_author_agent(author_model),
            build_review_loop(reviewer_model),
            FinalizeAgent(name="finalize", kind="monthly"),
        ],
        after_agent_callback=persist_visit_to_memory,
    )
