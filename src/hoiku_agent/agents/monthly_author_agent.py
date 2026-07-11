"""月案 作成AI（中身の決定＝agentic 層・責務②）。

設計コンテキスト §3「月案は日誌の集積に乗せる」/ §6（作成AI＝単一 LlmAgent）/ §10（L2 還流）。
保育経過記録・要録の作成AIと対称に、月案も**単一 LlmAgent**で構築する（内部を多層化しない＝§4/§6。
巡回＝再作成は harness の `build_authoring_loop` が日誌と共用で担う）。違いは instruction（月案スキーマ）と、
前月集積（L2 還流）を読む点だけ。

月案 author は reference_policy の既定を踏まえて fetch_reference で前月日誌を選択取得し、
その応答と recall_child_history を突き合わせ「前月の子どもの姿／
評価・反省」を要約する（集計＝harness／要約＝author の責務分離・§10）。

"型"（必須欄・年齢分岐タグ・整形）は harness（schema_check.validate_monthly_fields / draft.write_monthly_draft）
が確定段で保証するので、ここは「中身」に集中する。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from google.adk.agents import LlmAgent

from ..models import build_model
from ..schemas.policy import PolicyScope
from ..tools import ask_caregiver, fetch_reference, recall_child_history, search_guideline
from .instructions import build_author_instruction
from .prompts import MONTHLY_AUTHOR_INSTRUCTION

if TYPE_CHECKING:
    from google.adk.models import BaseLlm


def build_monthly_author_agent(model: str | BaseLlm | None = None) -> LlmAgent:
    """月案 作成AI（単一 LlmAgent）を構築して返す。巡回（再作成）は harness の authoring_loop が担う（§6/§7）。

    Args:
        model: 使用するモデル。既定（None）は build_model()（settings.gemini_model を
            model_location＝global に固定した Gemini。§11／models.py）。
            決定論E2E（tests/test_e2e/）では FakeLlm 等の BaseLlm を注入する差込口（§16）。

    日誌 author との違い: validate_fields ツール（DiaryEntry 用の自己点検）は配線しない。月案の確定
    validation は harness（validate_monthly_fields）が末尾で決定的に行う（§6・自己点検ツールの月案版は
    実需が出るまで増やさない＝ツールを 4–8 個に絞る原則）。output_key は日誌と共通の "draft"
    （後段 finalize が kind="monthly" で MonthlyPlan として復元する）。
    """
    return LlmAgent(
        name="monthly_author",
        model=model if model is not None else build_model(),
        # 文書作成指針と参照 source の既定を提示し、本文は fetch_reference で選択取得する（§5）。
        instruction=build_author_instruction(MONTHLY_AUTHOR_INSTRUCTION, PolicyScope.月案),
        tools=[
            fetch_reference,
            recall_child_history,  # その子の前回までの像（前月連続性＝§9）
            search_guideline,
            ask_caregiver,
        ],
        output_key="draft",  # 月案下書きを state["draft"] に格納（finalize が MonthlyPlan で復元）
    )
