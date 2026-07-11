"""harness：doc_type 分岐ルータ（決定的）。

設計コンテキスト §5「harness＝どの欄を・何の書類か」/ §10「doc_type／年齢分岐」/ §18/§19。
AI 生成書類の種別（個別月案 / クラス月案 / 保育経過記録 / 保育要録）で実行するパイプラインを決定的に
振り分ける。分岐は LLM ではなく harness の制御（state["doc_type"] を読むだけ・"何を書くか" の判断は
配下の LlmAgent）。**保育日誌は AI 生成を退役（手入力＝web で AI を通さない・ヒアリング 2026-07）**した
ためルータに載らない。

root_agent（agent.py）の実体。`adk run` / `adk web` は doc_type を state に入れないため**既定は
クラス月案**（§18＝園の実様式・product は doc_type を明示するので既定に来るのは dev 用途だけ）。各書類を
回すときは呼び出し側が state["doc_type"] と seed を渡す（scripts/run_class_monthly.py・run_monthly.py 等）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, AsyncGenerator

from google.adk.agents import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event
from google.adk.utils.context_utils import Aclosing

from .child_record import build_child_record_pipeline
from .class_monthly import build_class_monthly_pipeline
from .monthly import build_monthly_pipeline
from .youroku import build_nursery_record_pipeline

if TYPE_CHECKING:
    from google.adk.models import BaseLlm

_MONTHLY = "monthly_plan_pipeline"
_CLASS_MONTHLY = "class_monthly_pipeline"
_CHILD_RECORD = "child_record_pipeline"
_NURSERY_RECORD = "nursery_record_pipeline"
# 既定（doc_type 未設定／未知）＝クラス月案。保育日誌は AI 生成を退役したため（手入力＝web で AI を
# 通さない）ここには載らない。product は doc_type を明示するので既定に来るのは adk run/web の dev 用途だけ。
_DEFAULT = _CLASS_MONTHLY


class DocTypeRouter(BaseAgent):
    """state["doc_type"] で月案／クラス月案／保育経過記録／保育要録パイプラインを振り分ける（決定的・§10/§18/§19）。

    doc_type=="月案" は個別月案、"クラス月案" はクラス月案（園の実様式・§18）、"保育経過記録" は保育経過記録、
    "保育要録" は要録（L4）のパイプラインへ。**保育日誌は AI 生成を退役**（手入力＝web の docedit→finalize_entry）
    したためルータには載らない。doc_type 未設定/未知の既定はクラス月案（product は doc_type を明示する）。選んだ
    サブパイプラインの確定処理はそのまま委譲する。保育士承認後のMemory Bank書き戻しは生成後の
    `/api/records/approve` に一本化し、ルータ／パイプラインからは発火しない。
    """

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        doc_type = (ctx.session.state.get("doc_type") or "").strip()
        target_name = {
            "月案": _MONTHLY,
            "クラス月案": _CLASS_MONTHLY,
            "保育経過記録": _CHILD_RECORD,
            "保育要録": _NURSERY_RECORD,
        }.get(doc_type, _DEFAULT)
        target = next(a for a in self.sub_agents if a.name == target_name)
        async with Aclosing(target.run_async(ctx)) as agen:
            async for event in agen:
                yield event


def build_root_agent(
    author_model: str | BaseLlm | None = None,
    reviewer_model: str | BaseLlm | None = None,
) -> DocTypeRouter:
    """doc_type 分岐ルータ（root_agent の実体）を構築する（§10/§19）。

    月案・クラス月案・保育経過記録・保育要録のパイプラインを子に持ち、doc_type で選ぶ（保育日誌は手入力＝
    AI 生成を退役したため子に持たない）。author_model/reviewer_model は通常 None（実 Gemini）。テストでは
    FakeLlm を各パイプラインへ注入できる。
    """
    monthly = build_monthly_pipeline(author_model, reviewer_model)
    class_monthly = build_class_monthly_pipeline(author_model, reviewer_model)
    child_record = build_child_record_pipeline(author_model, reviewer_model)
    nursery_record = build_nursery_record_pipeline(author_model, reviewer_model)
    return DocTypeRouter(
        name="hoiku_root",
        sub_agents=[monthly, class_monthly, child_record, nursery_record],
    )
