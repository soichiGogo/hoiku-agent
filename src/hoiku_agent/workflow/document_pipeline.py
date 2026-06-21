"""ワークフロー層（型の保証）。

プロダクト方針 §2：書類作成の手順（どの書式で・どの順で・必須項目を満たすか）は
"変わらない部分"。ここを ADK のワークフローエージェント（Sequential / Loop）で組み、
「文書というモノを作成する」精度を保証する。中身の決定は配下の LlmAgent に委ねる。

パイプライン:
    author（作成・Agentic RAG / 不足は質問）
      → review_loop（レビューAIがOKを出すまで巡回）

TODO(設計):
- レビュー結果が APPROVED かを判定して LoopAgent を抜ける終了条件（escalation）を実装
- 「保育士OK」のHITL関門を author と review の間に明示的に置く（プロダクト方針 §1 process）
- 出力フォーマット（書式・必須項目充足）の最終バリデーションを末尾に追加
"""

from __future__ import annotations

from google.adk.agents import LoopAgent, SequentialAgent

from ..agents import build_author_agent, build_review_agent

MAX_REVIEW_ITERATIONS = 3


def build_document_pipeline() -> SequentialAgent:
    """書類作成の型を保証するルートパイプラインを構築する。"""
    author = build_author_agent()
    reviewer = build_review_agent()

    # レビューAIがOKを出すまで（最大 N 巡）改善を回す。
    # TODO: reviewer の出力が APPROVED なら早期終了する判定エージェントを差し込む。
    review_loop = LoopAgent(
        name="review_loop",
        sub_agents=[reviewer],
        max_iterations=MAX_REVIEW_ITERATIONS,
    )

    return SequentialAgent(
        name="document_pipeline",
        sub_agents=[author, review_loop],
    )
