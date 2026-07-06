"""クラス月案 作成AI（中身の決定＝agentic 層・責務②）。

設計コンテキスト §3「月案は日誌の集積に乗せる」/ §6（作成AI＝単一 LlmAgent）/ §10（L2 還流）/
§18（園の実様式）。個別月案（monthly_author_agent.py）と対称に、**園の実様式のクラス月案**も単一
LlmAgent で構築する（内部を多層化しない・巡回＝再作成は harness の `build_authoring_loop` が日誌/月案と
共用で担う）。違いは instruction（ClassMonthlyPlan スキーマ＝区分×領域グリッド＋0–2 の個人目標）だけで、
前月集積（L2 還流）を読む点は個別月案と同じ（scope も月案を流用＝指針カードの勘所を共有）。

"型"（必須欄・グリッド正準7行・整形）は harness（schema_check.validate_class_monthly_fields /
draft.write_class_monthly_draft）が確定段で保証するので、ここは「中身」に集中する。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from google.adk.agents import LlmAgent

from ..models import build_model
from ..schemas.policy import PolicyScope
from ..tools import ask_caregiver, recall_child_history, search_guideline
from .instructions import build_author_instruction
from .prompts import CLASS_MONTHLY_AUTHOR_INSTRUCTION

if TYPE_CHECKING:
    from google.adk.models import BaseLlm


def build_class_monthly_author_agent(model: str | BaseLlm | None = None) -> LlmAgent:
    """クラス月案 作成AI（単一 LlmAgent）を構築して返す。巡回は harness の authoring_loop が担う（§6/§18）。

    Args:
        model: 使用するモデル。既定（None）は build_model()（settings.gemini_model を model_location＝
            global に固定した Gemini。§11／models.py）。決定論E2E では FakeLlm 等の BaseLlm を注入する。

    指針 scope は個別月案と同じ PolicyScope.月案 を流用する（クラス月案専用 scope を増やさず月案の勘所を
    共有＝scope の増殖を避ける）。前月集積（state["prev_month_digest"]）を prompt 冒頭へ前置注入する点も
    個別月案と共通。output_key は日誌/月案と共通の "draft"（後段 finalize が kind="class_monthly" で
    ClassMonthlyPlan として復元する）。
    """
    return LlmAgent(
        name="class_monthly_author",
        model=model if model is not None else build_model(),
        # 文書作成指針（共通＋月案）＋前月集積（prev_month_digest）＋前月の振り返り（prev_month_reflections
        # ＝評価・反省・決定B）を prompt 冒頭へ前置注入（§5/§10）。
        instruction=build_author_instruction(
            CLASS_MONTHLY_AUTHOR_INSTRUCTION,
            PolicyScope.月案,
            digest_key="prev_month_digest",
            digest_label="前月",
            reflections_key="prev_month_reflections",
        ),
        tools=[
            recall_child_history,
            search_guideline,
            ask_caregiver,
        ],
        output_key="draft",  # クラス月案下書きを state["draft"] に格納（finalize が ClassMonthlyPlan で復元）
    )
