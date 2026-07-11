"""保育要録 作成AI（中身の決定＝agentic 層・責務②）。

設計コンテキスト §6（作成AI＝単一 LlmAgent）/ §19（集積階層の最終段 L4＝最終年度の保育経過記録を集積）。
日誌・月案・保育経過記録の作成AIと対称に、保育要録も**単一 LlmAgent**で構築する（内部を多層化しない＝§4/§6。
巡回＝再作成は harness の `build_authoring_loop` が共用で担う）。違いは instruction（要録スキーマ・年長=5領域・
**開示前提＝小学校への引き継ぎ＋保護者開示**・「最終年度に至るまでの育ち」の複数年叙述）と、最終年度の
保育経過記録の集積（L4 還流）を読む点。

要録 author は reference_policy に従ってそれまでの保育経過記録を fetch_reference で選択取得し、
その応答と recall_child_history を
突き合わせ「保育の展開と子どもの育ち／個人の重点／最終年度に至るまでの育ち」を叙述する（集計＝harness／要約＝author・§10/§19）。

"型"（必須欄・年齢分岐タグ・整形）は harness（validate_nursery_record_fields / write_nursery_record_draft）
が確定段で保証するので、ここは「中身」に集中する。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from google.adk.agents import LlmAgent

from ..models import build_model
from ..schemas.policy import PolicyScope
from ..tools import ask_caregiver, fetch_reference, recall_child_history, search_guideline
from .instructions import build_author_instruction
from .prompts import NURSERY_RECORD_AUTHOR_INSTRUCTION

if TYPE_CHECKING:
    from google.adk.models import BaseLlm


def build_nursery_record_author_agent(model: str | BaseLlm | None = None) -> LlmAgent:
    """保育要録 作成AI（単一 LlmAgent）を構築して返す。巡回は harness の authoring_loop が担う（§6/§7）。

    Args:
        model: 使用するモデル。既定（None）は build_model()（settings.gemini_model を
            model_location＝global に固定した Gemini。§11／models.py）。
            決定論E2E（tests/test_e2e/）では FakeLlm 等の BaseLlm を注入する差込口（§16）。

    文書作成指針と reference_policy の既定 source は InstructionProvider が提示し、参照本文は
    fetch_reference で取得する（§5）。日誌は要録の候補に加えない。validate_fields ツールは配線せず、要録の
    確定 validation は harness（validate_nursery_record_fields）が末尾で決定的に行う（§6・ツールを 4–8 個に絞る原則）。
    output_key は日誌・月案・保育経過記録と共通の "draft"（後段 finalize が kind="nursery_record" で復元する）。
    """
    return LlmAgent(
        name="nursery_record_author",
        model=model if model is not None else build_model(),
        # 文書作成指針と参照 source の既定を提示し、本文は fetch_reference で選択取得する（§5）。
        instruction=build_author_instruction(
            NURSERY_RECORD_AUTHOR_INSTRUCTION,
            PolicyScope.保育要録,
        ),
        tools=[
            fetch_reference,
            recall_child_history,  # その子の入所時からの像（要録は入所〜最終年度の連続性が要＝§9）
            search_guideline,
            ask_caregiver,
        ],
        output_key="draft",  # 要録下書きを state["draft"] に格納（finalize が NurseryRecord で復元）
    )
