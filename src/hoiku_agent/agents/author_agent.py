"""作成AI（中身の決定＝agentic 層・責務②）。

設計コンテキスト §6：作成AI＝**単一 LlmAgent**。gather → act → verify は instruction の手順＋
ADK の tool-use ループ（モデルがツールを呼ばなくなるまでの自然な反復）で表現する。
**LoopAgent では包まない**（多層化回避＝§4 と整合）。不足検知 → ask_caregiver → 再起案の反復は
この tool-calling ループ内で完結させる。収集・質問生成・起案を別エージェントに分けない。

"型"（必須項目の充足・整形）は harness が保証するので、ここは「中身」に集中する。
"""

from __future__ import annotations

from google.adk.agents import LlmAgent

from ..config import settings
from ..tools import (
    ask_caregiver,
    get_child_memory,
    read_policy,
    search_guideline,
    search_records,
    validate_fields,
)
from .prompts import AUTHOR_INSTRUCTION


def build_author_agent() -> LlmAgent:
    """作成AI（単一 LlmAgent）を構築して返す。LoopAgent では包まない（§6）。"""
    return LlmAgent(
        name="author",
        model=settings.gemini_model,
        instruction=AUTHOR_INSTRUCTION,
        tools=[
            search_records,
            search_guideline,
            read_policy,
            get_child_memory,
            ask_caregiver,
            validate_fields,  # 生成途中の自己点検（最終確定は harness）
        ],
        output_key="draft",  # 生成した下書きを state["draft"] に格納
    )
