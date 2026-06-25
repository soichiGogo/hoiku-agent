"""harness：作成パイプラインの順序制御（決定的）。

設計コンテキスト §4「一階＝作成本体」/ §5「harness の物理マッピング」/ §7（レビュー早期終了）。
旧 workflow/document_pipeline.py の昇格先。author → review_loop → 確定（HITLゲート）の
"順序" と "型の保証" をここで決定的に組む。中身の決定は配下の LlmAgent に委ねる。

この層は決定的：LLM プロンプトや「何を書くか」の判断は書かない（それは agents/ の責務）。
APPROVED 早期終了の "判定"（ApprovalGate）と確定処理の "実行"（FinalizeAgent）はここ＝決定的に
行い、レビュー内容の "生成" は reviewer、確定の純ロジックは harness/finalize.py に置く（実体は1つ）。

パイプライン（root_agent の実体）:
    author（作成・Agentic RAG / 不足は ask_caregiver）→ state["draft"]
      → review_loop（reviewer→ApprovalGate を最大 N 巡。APPROVED で escalate 早期終了）
      → finalize（確定 validate_fields/write_draft を末尾で決定的実行・HITL 承認フラグを立てる）

v0 の設計上の形（§6/§7）:
- author は単一（LoopAgent に包まない）。再起案は author 自身の tool-use ループ内で完結。
- review_loop は reviewer の巡回＋ApprovalGate の早期終了。APPROVED が出なければ max_iterations 後に
  finalize へ抜け、指摘（state["review"]）は保育士の確定（HITL）に供される（最終OKは人＝§7）。

v0 スコープ（§3「日誌先行 → 月案は日誌の集積に乗せる」）:
- このパイプラインは **保育日誌（0–2 個別）のみ** を稼働させる。月案パスと L2 還流
  （`aggregate.aggregate_by_child` → state["prev_month_digest"] → 月案 author の gather）は **次フェーズ**。
  `aggregate_by_child` は集計の決定的実体としてテスト済みだが、まだどのパイプラインにも配線していない。
- ADK 2.3.0 では LoopAgent/SequentialAgent が deprecated（将来 Workflow へ）。設計（§6/§7）が前提とする
  API であり、2.3.0 の Workflow 代替は非公開のため v0 はこのまま使う（中期 TODO で移行）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, AsyncGenerator

from google.adk.agents import BaseAgent, LoopAgent, SequentialAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event, EventActions
from google.genai import types

from ..agents import build_author_agent, build_review_agent
from .finalize import finalize_document

if TYPE_CHECKING:
    from google.adk.models import BaseLlm

MAX_REVIEW_ITERATIONS = 3
_APPROVED_TOKEN = "APPROVED"


def _model_content(text: str) -> types.Content:
    return types.Content(role="model", parts=[types.Part(text=text)])


def is_approved(review: object) -> bool:
    """reviewer 出力が承認（APPROVED）か（早期終了の決定ロジック・決定的）。

    APPROVED 早期終了の "判定" は harness の決定的ロジック（§7/§16）。純関数として切り出し
    LLM 非依存にテストできるようにする。

    reviewer は判定を **最初の行** に APPROVED / NEEDS_REVISION で書く契約（prompts.py）。
    部分一致（`"approved" in text`）だと指摘本文の散文（例「approved とは言えない」「NOT APPROVED」）に
    誤反応して未承認なのに早期終了してしまうため、最初の非空行が APPROVED で始まるかで判定する。
    否定形（NOT APPROVED / 未APPROVED）は APPROVED で「始まらない」ので自然に弾かれる。
    """
    if not isinstance(review, str):
        return False
    for line in review.splitlines():
        head = line.strip().lstrip("*#>-・ 　").strip().upper()
        if not head:
            continue
        return head.startswith(_APPROVED_TOKEN)
    return False


class ApprovalGate(BaseAgent):
    """reviewer の出力（state["review"]）が APPROVED なら LoopAgent を早期終了させる（§7）。

    早期終了の "判定" は決定的（harness）に行う。レビュー内容の "生成" は reviewer の責務。
    """

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        if is_approved(ctx.session.state.get("review")):
            yield Event(
                author=self.name,
                content=_model_content(
                    "レビュー承認（APPROVED）を検知。レビュー巡回を終了します。"
                ),
                actions=EventActions(escalate=True),
            )
        # 未承認なら何も yield せず、LoopAgent の次の巡回へ（max_iterations で頭打ち）。


class FinalizeAgent(BaseAgent):
    """確定処理（決定的）：ドラフトを復元し validate_fields/write_draft を末尾で実行する（§6）。

    結果（整形済み確定下書き・違反一覧・確定下書き待ちの HITL フラグ）を state へ書き戻す。
    最終OK（確定）は保育士＝HITL（§7）なので、ここでは "確定下書き＋承認待ち" までを作る。
    """

    template_ref: str | None = None

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        draft = ctx.session.state.get("draft") or ""
        result = finalize_document(draft, template_ref=self.template_ref)

        state_delta = {
            "final_document": result.formatted,
            "validation": result.problems,
            "finalize_parse_error": result.parse_error,
            # 最終OKは人（§7）：確定下書きは出来たが、確定は保育士の承認を待つ。
            "awaiting_caregiver_approval": True,
        }

        if result.parse_error:
            msg = (
                "【確定処理】ドラフトの構造化に失敗しました："
                f"{result.parse_error}\n"
                "→ author の最終出力に DiaryEntry の JSON（```json フェンス）が必要です。"
            )
        elif result.problems:
            msg = (
                "【確定処理】必須欄/年齢分岐に不足があります（保育士の確認が必要）:\n- "
                + "\n- ".join(result.problems)
            )
        else:
            msg = (
                "【確定処理】型チェックを通過しました。以下が確定下書きです"
                "（最終確定は保育士＝HITL）:\n\n" + (result.formatted or "")
            )

        yield Event(
            author=self.name,
            content=_model_content(msg),
            actions=EventActions(state_delta=state_delta),
        )


def build_review_loop(reviewer_model: str | BaseLlm | None = None) -> LoopAgent:
    """reviewer の巡回＋APPROVED 早期終了（ApprovalGate）の LoopAgent を構築する（§7）。

    reviewer_model は通常 None（＝settings.gemini_model）。決定論E2E では FakeLlm を注入する。
    """
    return LoopAgent(
        name="review_loop",
        sub_agents=[build_review_agent(reviewer_model), ApprovalGate(name="approval_gate")],
        max_iterations=MAX_REVIEW_ITERATIONS,
    )


def build_document_pipeline(
    author_model: str | BaseLlm | None = None,
    reviewer_model: str | BaseLlm | None = None,
) -> SequentialAgent:
    """書類作成の型を保証するルートパイプラインを構築する（root_agent の実体）。

    author_model / reviewer_model は通常 None（＝settings.gemini_model で実 Gemini を使う）。
    決定論E2E（tests/test_e2e/）では各段に FakeLlm を注入し、LLM/GCP 非依存に
    author→review_loop→finalize の結合（順序・早期終了・確定/HITLフラグ）を検証する（§16）。
    root_agent（agent.py）は引数なしで呼ぶため本番挙動は不変。
    """
    return SequentialAgent(
        name="document_pipeline",
        sub_agents=[
            build_author_agent(author_model),
            build_review_loop(reviewer_model),
            FinalizeAgent(name="finalize"),
        ],
    )
