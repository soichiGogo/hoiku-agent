"""作成AI（中身の決定＝agentic 層・責務②）。

設計コンテキスト §6：作成AI＝**単一 LlmAgent**（内部を多層化しない）。gather → act → verify は
instruction の手順＋ADK の tool-use ループ（モデルがツールを呼ばなくなるまでの自然な反復）で表現する。
収集・質問生成・起案を別エージェントに分けない。

巡回（レビューの差し戻しでの再作成）は harness が担う：harness/pipeline.py の `build_authoring_loop` が
[作成 → レビュー → ApprovalGate] を1巡とする LoopAgent に**この author を包み**、NEEDS_REVISION の
とき次巡で author が指摘点を直して再提出する（「巡回保証が要る」と判断したための設計＝旧 v0 は author を
ループに包まなかった）。再作成時の挙動（白紙から作り直さない・同じ不足で再質問しない）は prompts.py。

"型"（必須項目の充足・整形）は harness が保証するので、ここは「中身」に集中する。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from google.adk.agents import LlmAgent

from ..models import build_model
from ..tools import (
    ask_caregiver,
    read_policy,
    recall_child_history,
    search_guideline,
    validate_fields,
)
from .prompts import AUTHOR_INSTRUCTION

if TYPE_CHECKING:
    from google.adk.models import BaseLlm


def build_author_agent(model: str | BaseLlm | None = None) -> LlmAgent:
    """作成AI（単一 LlmAgent）を構築して返す。巡回（再作成）は harness の authoring_loop が担う（§6/§7）。

    Args:
        model: 使用するモデル。既定（None）は build_model()（settings.gemini_model を
            model_location＝global に固定した Gemini。§11／models.py）。
            決定論E2E（tests/test_e2e/）では FakeLlm 等の BaseLlm インスタンスを注入し、
            LLM/GCP 非依存に author→review→finalize の結合を検証するための差込口（§16）。
            本番の root_agent は引数なしで呼ぶため挙動は不変。
    """
    return LlmAgent(
        name="author",
        model=model if model is not None else build_model(),
        instruction=AUTHOR_INSTRUCTION,
        tools=[
            recall_child_history,  # 同じ子の前回までの姿（継続性は必ずこれ＝§9・B方針）
            search_guideline,
            read_policy,
            ask_caregiver,
            validate_fields,  # 生成途中の自己点検（最終確定は harness）
        ],
        output_key="draft",  # 生成した下書きを state["draft"] に格納
    )
