"""保育経過記録 作成AI（中身の決定＝agentic 層・責務②）。

設計コンテキスト §6（作成AI＝単一 LlmAgent）/ §19（ヒアリング反映 2026-07：保育経過記録＝L3 集積）。
日誌・月案の作成AIと対称に、保育経過記録も**単一 LlmAgent**で構築する（内部を多層化しない＝§4/§6。
巡回＝再作成は harness の `build_authoring_loop` が日誌・月案と共用で担う）。違いは instruction
（保育経過記録スキーマ・**開示前提の肯定的・非断定的表現**）と、期間集積（L3 還流）を読む点だけ。

保育経過記録 author は reference_policy に従って期間日誌と前回までの保育経過記録を fetch_reference で
選択取得し、その応答と recall_child_history を
突き合わせ「発達の経過／総合所見」を領域別に叙述する（集計＝harness／要約＝author・§10/§19）。

"型"（必須欄・年齢分岐タグ・整形）は harness（validate_child_record_fields / write_child_record_draft）
が確定段で保証するので、ここは「中身」に集中する。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from google.adk.agents import LlmAgent

from ..models import build_model
from ..schemas.policy import PolicyScope
from ..tools import ask_caregiver, fetch_reference, recall_child_history, search_guideline
from .instructions import build_author_instruction
from .prompts import CHILD_RECORD_AUTHOR_INSTRUCTION

if TYPE_CHECKING:
    from google.adk.models import BaseLlm


def build_child_record_author_agent(model: str | BaseLlm | None = None) -> LlmAgent:
    """保育経過記録 作成AI（単一 LlmAgent）を構築して返す。巡回は harness の authoring_loop が担う（§6/§7）。

    Args:
        model: 使用するモデル。既定（None）は build_model()（settings.gemini_model を
            model_location＝global に固定した Gemini。§11／models.py）。
            決定論E2E（tests/test_e2e/）では FakeLlm 等の BaseLlm を注入する差込口（§16）。

    月案 author と同じく validate_fields ツール（DiaryEntry 用の自己点検）は配線しない。保育経過記録の確定
    validation は harness（validate_child_record_fields）が末尾で決定的に行う（§6・ツールを 4–8 個に
    絞る原則）。output_key は日誌・月案と共通の "draft"（後段 finalize が kind="child_record" で復元する）。
    """
    return LlmAgent(
        name="child_record_author",
        model=model if model is not None else build_model(),
        # 文書作成指針と参照 source の既定を提示し、本文は fetch_reference で選択取得する（§5）。
        instruction=build_author_instruction(
            CHILD_RECORD_AUTHOR_INSTRUCTION,
            PolicyScope.保育経過記録,
        ),
        tools=[
            fetch_reference,
            recall_child_history,  # その子の前回までの像（期の連続性＝§9）
            search_guideline,
            ask_caregiver,
        ],
        output_key="draft",  # 保育経過記録下書きを state["draft"] に格納（finalize が ChildRecord で復元）
    )
