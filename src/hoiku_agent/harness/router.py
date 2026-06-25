"""harness：doc_type 分岐ルータ（決定的）。

設計コンテキスト §5「harness＝どの欄を・何の書類か」/ §10「doc_type／年齢分岐」。
書類種別（保育日誌 / 月案）で実行するパイプラインを決定的に振り分ける。分岐は LLM ではなく
harness の制御（state["doc_type"] を読むだけ・"何を書くか" の判断は配下の LlmAgent）。

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

from .monthly import build_monthly_pipeline
from .pipeline import build_document_pipeline

if TYPE_CHECKING:
    from google.adk.models import BaseLlm

_DIARY = "document_pipeline"
_MONTHLY = "monthly_plan_pipeline"


class DocTypeRouter(BaseAgent):
    """state["doc_type"] で日誌／月案パイプラインを振り分ける（決定的・§10）。

    既定は保育日誌（doc_type 未設定＝既存デモの挙動）。doc_type=="月案" のときだけ月案パイプラインへ。
    選んだサブパイプラインの確定処理（after_agent_callback の書き戻し含む）はそのまま委譲する。
    """

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        doc_type = (ctx.session.state.get("doc_type") or "").strip()
        target_name = _MONTHLY if doc_type == "月案" else _DIARY
        target = next(a for a in self.sub_agents if a.name == target_name)
        async with Aclosing(target.run_async(ctx)) as agen:
            async for event in agen:
                yield event


def build_root_agent(
    author_model: str | BaseLlm | None = None,
    reviewer_model: str | BaseLlm | None = None,
) -> DocTypeRouter:
    """doc_type 分岐ルータ（root_agent の実体）を構築する（§10）。

    日誌・月案の両パイプラインを子に持ち、doc_type で選ぶ。author_model/reviewer_model は通常 None
    （実 Gemini）。テストでは FakeLlm を両パイプラインへ注入できる。
    """
    diary = build_document_pipeline(author_model, reviewer_model)
    monthly = build_monthly_pipeline(author_model, reviewer_model)
    return DocTypeRouter(name="hoiku_root", sub_agents=[diary, monthly])
