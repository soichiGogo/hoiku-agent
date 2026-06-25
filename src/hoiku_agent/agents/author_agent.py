"""作成AI（中身の決定＝agentic 層・責務②）。

設計コンテキスト §6：作成AI＝**単一 LlmAgent**。gather → act → verify は instruction の手順＋
ADK の tool-use ループ（モデルがツールを呼ばなくなるまでの自然な反復）で表現する。
**LoopAgent では包まない**（多層化回避＝§4 と整合）。不足検知 → ask_caregiver → 再起案の反復は
この tool-calling ループ内で完結させる。収集・質問生成・起案を別エージェントに分けない。

"型"（必須項目の充足・整形）は harness が保証するので、ここは「中身」に集中する。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from google.adk.agents import LlmAgent

from ..config import settings
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
    """作成AI（単一 LlmAgent）を構築して返す。LoopAgent では包まない（§6）。

    Args:
        model: 使用するモデル。既定（None）は settings.gemini_model（実 Gemini）。
            決定論E2E（tests/test_e2e/）では FakeLlm 等の BaseLlm インスタンスを注入し、
            LLM/GCP 非依存に author→review→finalize の結合を検証するための差込口（§16）。
            本番の root_agent は引数なしで呼ぶため挙動は不変。
    """
    return LlmAgent(
        name="author",
        model=model if model is not None else settings.gemini_model,
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
