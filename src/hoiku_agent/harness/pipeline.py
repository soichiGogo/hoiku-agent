"""harness：作成パイプラインの順序制御（決定的）。

設計コンテキスト §4「一階＝作成本体」/ §5「harness の物理マッピング」に対応。
旧 workflow/document_pipeline.py の昇格先。author → review_loop → 確定（HITLゲート）の
"順序" と "型の保証" をここで決定的に組む。中身の決定は配下の LlmAgent に委ねる。

この層は決定的：LLM プロンプトや「何を書くか」の判断は書かない（それは agents/ の責務）。
APPROVED 早期終了の "判定" もここ（ループ制御＝決定的）で行い、"レビュー内容の生成" は
reviewer に委ねる。

パイプライン:
    author（作成・Agentic RAG / 不足は質問）
      → review_loop（レビューAIが APPROVED を出すまで巡回・早期終了）
      → 確定（保育士OK の HITL ゲート）／ 出力フォーマットの最終 validation

TODO(設計):
- reviewer 出力が APPROVED かを判定して LoopAgent を抜ける終了条件（escalation）を実装。
- 「保育士OK」の HITL 関門を author と review の確定段で明示的に置く（§6 HITL）。
- 末尾に validate_fields（harness.schema_check）と write_draft（harness.draft）の確定実行を追加。
"""

from __future__ import annotations

from google.adk.agents import LoopAgent, SequentialAgent

from ..agents import build_author_agent, build_review_agent

MAX_REVIEW_ITERATIONS = 3


def build_document_pipeline() -> SequentialAgent:
    """書類作成の型を保証するルートパイプラインを構築する（root_agent の実体）。"""
    author = build_author_agent()
    reviewer = build_review_agent()

    # レビューAIが APPROVED を出すまで（最大 N 巡）改善を回す。
    # TODO: reviewer の出力が APPROVED なら早期終了する判定（escalation）を差し込む（§7）。
    review_loop = LoopAgent(
        name="review_loop",
        sub_agents=[reviewer],
        max_iterations=MAX_REVIEW_ITERATIONS,
    )

    return SequentialAgent(
        name="document_pipeline",
        sub_agents=[author, review_loop],
    )
