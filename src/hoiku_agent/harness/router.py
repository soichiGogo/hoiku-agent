"""harness：doc_type 分岐ルータ（決定的）。

設計コンテキスト §5「harness＝どの欄を・何の書類か」/ §10「doc_type／年齢分岐」。
書類種別（保育日誌 / 月案 / 児童票 / 保育要録）で実行するパイプラインを決定的に振り分ける。分岐は
LLM ではなく harness の制御（state["doc_type"] を読むだけ・"何を書くか" の判断は配下の LlmAgent）。

root_agent（agent.py）の実体。`adk run` / `adk web` は doc_type を state に入れないため**既定は
保育日誌**（v0 日誌先行＝§3。既存デモの挙動は不変）。月案を回すときは呼び出し側が
state["doc_type"]="月案"（と前月日誌 state["prev_month_entries"]）を seed する（scripts/run_monthly.py）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, AsyncGenerator

from google.adk.agents import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event
from google.adk.utils.context_utils import Aclosing

from .child_record import build_child_record_pipeline
from .monthly import build_monthly_pipeline
from .pipeline import build_document_pipeline
from .youroku import build_nursery_record_pipeline

if TYPE_CHECKING:
    from google.adk.models import BaseLlm

_DIARY = "document_pipeline"
_MONTHLY = "monthly_plan_pipeline"
_CHILD_RECORD = "child_record_pipeline"
_NURSERY_RECORD = "nursery_record_pipeline"


class DocTypeRouter(BaseAgent):
    """state["doc_type"] で日誌／月案／児童票／保育要録パイプラインを振り分ける（決定的・§10/§19）。

    既定は保育日誌（doc_type 未設定＝既存デモの挙動）。doc_type=="月案" は月案、"児童票" は児童票、
    "保育要録" は要録（L4）のパイプラインへ。選んだサブパイプラインの確定処理（after_agent_callback の
    書き戻し含む）はそのまま委譲する。
    """

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        doc_type = (ctx.session.state.get("doc_type") or "").strip()
        if doc_type == "月案":
            target_name = _MONTHLY
        elif doc_type == "児童票":
            target_name = _CHILD_RECORD
        elif doc_type == "保育要録":
            target_name = _NURSERY_RECORD
        else:
            target_name = _DIARY
        target = next(a for a in self.sub_agents if a.name == target_name)
        async with Aclosing(target.run_async(ctx)) as agen:
            async for event in agen:
                yield event


def build_root_agent(
    author_model: str | BaseLlm | None = None,
    reviewer_model: str | BaseLlm | None = None,
) -> DocTypeRouter:
    """doc_type 分岐ルータ（root_agent の実体）を構築する（§10/§19）。

    日誌・月案・児童票のパイプラインを子に持ち、doc_type で選ぶ。author_model/reviewer_model は
    通常 None（実 Gemini）。テストでは FakeLlm を各パイプラインへ注入できる。
    """
    diary = build_document_pipeline(author_model, reviewer_model)
    monthly = build_monthly_pipeline(author_model, reviewer_model)
    child_record = build_child_record_pipeline(author_model, reviewer_model)
    nursery_record = build_nursery_record_pipeline(author_model, reviewer_model)
    return DocTypeRouter(
        name="hoiku_root",
        sub_agents=[diary, monthly, child_record, nursery_record],
    )
