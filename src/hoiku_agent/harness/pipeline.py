"""harness：作成パイプラインの順序制御（決定的）。

設計コンテキスト §4「一階＝作成本体」/ §5「harness の物理マッピング」/ §7（レビュー早期終了）。
旧 workflow/document_pipeline.py の昇格先。authoring_loop（作成→レビュー→ゲートを巡回）→ 確定
（HITLゲート）の "順序" と "型の保証" をここで決定的に組む。中身の決定は配下の LlmAgent に委ねる。

この層は決定的：LLM プロンプトや「何を書くか」の判断は書かない（それは agents/ の責務）。
APPROVED 早期終了の "判定"（ApprovalGate）と確定処理の "実行"（FinalizeAgent）はここ＝決定的に
行い、レビュー内容の "生成" は reviewer、確定の純ロジックは harness/finalize.py に置く（実体は1つ）。

日誌パイプライン（`build_document_pipeline`。root_agent は `router.py` の `DocTypeRouter` で、これは
その配下の保育日誌サブパイプライン）:
    authoring_loop（[author → reviewer → ApprovalGate] を最大 N 巡）
      ├ author（作成・Agentic RAG / 不足は ask_caregiver）→ state["draft"]
      ├ reviewer（別視点で点検）→ state["review"]
      └ ApprovalGate（APPROVED なら escalate して早期終了。NEEDS_REVISION なら次巡で author が再作成）
      → finalize（確定 validate_fields/write_draft を末尾で決定的実行・HITL 承認フラグを立てる）
      → [after_agent_callback] persist_visit_to_memory（保育士の明示承認＋型成立のときのみ、来園
        セッションを子の長期メモリ＝Agent Engine Memory Bank へ書き戻す＝§9/§13「来園のたびに像が育つ」）

設計上の形（§6/§7）:
- author は単一 LlmAgent（内部を多層化しない）。ただし harness が [作成→レビュー→ゲート] を1巡とする
  LoopAgent（authoring_loop）に包み、NEEDS_REVISION のとき author が**指摘点だけ直して再提出**する
  （「巡回保証が要る」と判断したための設計転換＝旧 v0 は author をループに包まなかった。再質問しない
  revision mode は agents/prompts.py）。
- ApprovalGate は APPROVED で escalate して早期終了。出なければ max_iterations 後に finalize へ抜け、
  指摘（state["review"]）は保育士の確定（HITL）に供される（最終OKは人＝§7）。

スコープと関連パス（§3「日誌先行 → 月案は日誌の集積に乗せる」）:
- このファイルが組むのは **保育日誌（0–2 個別）** のパイプライン（`build_document_pipeline`）。
- 月案パスと L2 還流（`aggregate.aggregate_by_child` → state["prev_month_digest"] → 月案 author の
  gather）は `monthly.py`（`DigestPrepAgent` / `build_monthly_pipeline`）に実装済みで、`router.py` の
  `DocTypeRouter`（root_agent）が state["doc_type"] で日誌／月案へ決定的に振り分ける。`aggregate_by_child`
  は集計の決定的実体として `monthly.py` に配線済み（§3/§4/§10）。
- ADK 2.3.0 では LoopAgent/SequentialAgent が deprecated（将来 Workflow へ）。設計（§6/§7）が前提とする
  API であり、2.3.0 の Workflow 代替は非公開のため v0 はこのまま使う（中期 TODO で移行）。
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from typing import TYPE_CHECKING, AsyncGenerator

from google.adk.agents import BaseAgent, LoopAgent, SequentialAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event, EventActions
from google.genai import types

from ..agents import build_author_agent, build_review_agent
from .finalize import (
    finalize_child_record_document,
    finalize_document,
    finalize_monthly_document,
)

if TYPE_CHECKING:
    from google.adk.agents.callback_context import CallbackContext
    from google.adk.models import BaseLlm

MAX_REVIEW_ITERATIONS = 3
_APPROVED_TOKEN = "APPROVED"

# 真の承認ゲート（§9/§13）：保育士の明示承認を表す state キー。FinalizeAgent が立てる
# awaiting_caregiver_approval（承認待ち）に対し、保育士の確定アクションがこれを True にすると
# 来園が子の長期メモリへ書き戻される（_should_persist_visit）。SSOT としてここで一度だけ定義する。
CAREGIVER_APPROVAL_KEY = "caregiver_approved"

# 記録日（日誌）は harness が所有する決定的メタデータ（§5）。保育士/UI が指定する場合はこの
# state キーに ISO 文字列または date を載せる。未指定なら確定時に「本日」を採る（FinalizeAgent）。
DOC_DATE_KEY = "doc_date"


def _resolve_doc_date(raw: object) -> date:
    """state["doc_date"] を date に解決する（記録日の決定的解決＝clock はランタイム境界に置く）。

    date ならそのまま、ISO 文字列なら parse、未指定/不正なら本日を採る。LLM に日付を生成させず、
    ここで決定的に補完する（finalize.py を純関数に保つための現在日付の解決点＝§5）。
    """
    if isinstance(raw, date):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            return date.fromisoformat(raw.strip())
        except ValueError:
            pass
    return date.today()


def _model_content(text: str) -> types.Content:
    return types.Content(role="model", parts=[types.Part(text=text)])


def mark_caregiver_approved(approved: bool = True) -> dict:
    """保育士の確定（明示承認）を表す session state delta を返す（決定的・§9/§13）。

    真の承認ゲートの「保育士の確定アクション」を1箇所に集約する。アプリ層（server / 確定 UI / 確定ターン）が
    保育士の承認を受けたとき、この戻り値を session state に適用する（例: 確定エントリが state を更新して
    パイプラインの after_agent_callback を再評価する）。LLM は呼ばない（承認は人の行為であって AI の判断では
    ない＝§7）。

    Returns:
        {CAREGIVER_APPROVAL_KEY: approved} の state delta。
    """
    return {CAREGIVER_APPROVAL_KEY: approved}


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
                invocation_id=ctx.invocation_id,
                author=self.name,
                content=_model_content(
                    "レビュー承認（APPROVED）を検知。レビュー巡回を終了します。"
                ),
                actions=EventActions(escalate=True),
            )
        # 未承認なら何も yield せず、LoopAgent の次の巡回へ（max_iterations で頭打ち）。


class FinalizeAgent(BaseAgent):
    """確定処理（決定的）：ドラフトを復元し validate/write を末尾で実行する（§6）。

    結果（整形済み確定下書き・違反一覧・確定下書き待ちの HITL フラグ）を state へ書き戻す。
    最終OK（確定）は保育士＝HITL（§7）なので、ここでは "確定下書き＋承認待ち" までを作る。
    kind で日誌（diary）／月案（monthly）の確定ロジック（harness/finalize.py の実体）を差し替える。
    日誌の記録日（date）は harness が所有する決定的メタデータ（§5）：state["doc_date"]（無ければ本日）を
    解決して finalize に渡し、author 出力の date を上書きする（LLM に日付を生成させない＝雛形 echo 耐性）。
    """

    template_ref: str | None = None
    kind: str = (
        "diary"  # "diary"（DiaryEntry）/ "monthly"（MonthlyPlan）/ "child_record"（ChildRecord）
    )

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        draft = ctx.session.state.get("draft") or ""
        if self.kind == "monthly":
            result = finalize_monthly_document(draft, template_ref=self.template_ref)
            schema_label = "MonthlyPlan"
        elif self.kind == "child_record":
            result = finalize_child_record_document(draft, template_ref=self.template_ref)
            schema_label = "ChildRecord"
        else:
            doc_date = _resolve_doc_date(ctx.session.state.get(DOC_DATE_KEY))
            result = finalize_document(draft, template_ref=self.template_ref, doc_date=doc_date)
            schema_label = "DiaryEntry"

        state_delta = {
            "final_document": result.formatted,
            # 確定した書類を**構造化エントリ（dict）でも**残す。保育士の編集UI（web/）がこれを欄ごとの
            # 編集フォームに描き、編集後は finalize_entry で harness の検査/整形を再実行する（§11 presentation）。
            "final_entry": result.entry.model_dump(mode="json") if result.entry else None,
            "final_doc_kind": self.kind,
            "validation": result.problems,
            "finalize_parse_error": result.parse_error,
            # 最終OKは人（§7）：確定下書きは出来たが、確定は保育士の承認を待つ。
            "awaiting_caregiver_approval": True,
        }

        if result.parse_error:
            msg = (
                "【確定処理】ドラフトの構造化に失敗しました："
                f"{result.parse_error}\n"
                f"→ author の最終出力に {schema_label} の JSON（```json フェンス）が必要です。"
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
            invocation_id=ctx.invocation_id,
            author=self.name,
            content=_model_content(msg),
            actions=EventActions(state_delta=state_delta),
        )


def build_authoring_loop(
    author: BaseAgent,
    reviewer_model: str | BaseLlm | None = None,
) -> LoopAgent:
    """[作成 → レビュー → ApprovalGate] を1巡とする巡回 LoopAgent を構築する（§7）。

    NEEDS_REVISION のとき author が次巡で指摘点を直して再提出し、APPROVED で ApprovalGate が
    escalate して早期終了、出なければ max_iterations で頭打ち→（呼び出し側の）finalize へ抜ける。
    author は日誌／月案で差し替える（呼び出し側が build_author_agent / build_monthly_author_agent を渡す）。
    reviewer は日誌・月案で共用（reviewer_model は通常 None＝settings.gemini_model。決定論E2E では
    FakeLlm を注入する）。「巡回保証が要る」と判断したための設計（旧 v0 は author をループに包まなかった）。
    """
    return LoopAgent(
        name="authoring_loop",
        sub_agents=[
            author,
            build_review_agent(reviewer_model),
            ApprovalGate(name="approval_gate"),
        ],
        max_iterations=MAX_REVIEW_ITERATIONS,
    )


def _should_persist_visit(state: Mapping) -> bool:
    """保育士が確定下書きを明示承認したか（来園を子の長期メモリへ書き戻してよいか・決定的）。

    設計コンテキスト §9/§13：0–2 個別＝子ども別長期メモリは「来園のたびに像が育つ」。最終OKは人
    （§7）なので、書き戻しは「保育士の明示承認（真の承認ゲート）」で初めて起こす。書き戻しの "判定"
    は harness の決定的ロジック（純関数）として切り出し、LLM 非依存にテストできるようにする。

    True になる条件（すべて満たす）:
    1. **明示承認**：state["caregiver_approved"] is True（保育士の確定アクション＝CAREGIVER_APPROVAL_KEY）。
    2. **型成立**：parse 成功・違反0・整形出力あり（承認しても型不成立の下書きで像を汚さない）。

    型成立だけでは書き戻さない（保育士OK ≠ 自動確定）。承認は確定段（FinalizeAgent）が
    `awaiting_caregiver_approval=True` で待ち、保育士の確定ターンが `caregiver_approved=True` を state に
    立てる（mark_caregiver_approved／confirm エントリ）。未承認・未配線では書き戻さず素通り（降格）。
    """
    if state.get(CAREGIVER_APPROVAL_KEY) is not True:
        return False
    if state.get("finalize_parse_error"):
        return False
    if state.get("validation"):
        return False
    return bool(state.get("final_document"))


async def persist_visit_to_memory(callback_context: CallbackContext) -> None:
    """来園セッションを子の長期メモリ（Agent Engine Memory Bank）へ書き戻す（§9/§13）。

    pipeline の `after_agent_callback`（finalize の後段）として実行する。書き戻しの "実行" は
    ADK のマネージドメモリに委ね、harness は "判定（_should_persist_visit）" と配線だけを持つ
    （外部 I/O は managed サービス越し・LLM は呼ばない）。

    memory_service 未配線（ローカル / `agentengine://` 未指定）では ADK が `ValueError` を投げる。
    ライブ Memory Bank の一時障害も含め、書き戻しの失敗で日誌の実行を止めない＝降格する
    （tools の RAG/Memory と同じ哲学）。返り値 None＝finalize の出力を置き換えない。
    """
    if not _should_persist_visit(callback_context.state):
        return
    try:
        await callback_context.add_session_to_memory()
    except ValueError:
        return  # memory_service 未配線（ローカル/未接続）＝期待される降格
    except Exception:  # noqa: BLE001  ライブ Memory Bank 障害も降格（稼働を止めない）
        return


def build_document_pipeline(
    author_model: str | BaseLlm | None = None,
    reviewer_model: str | BaseLlm | None = None,
) -> SequentialAgent:
    """書類作成の型を保証するルートパイプラインを構築する（root_agent の実体）。

    author_model / reviewer_model は通常 None（＝settings.gemini_model で実 Gemini を使う）。
    決定論E2E（tests/test_e2e/）では各段に FakeLlm を注入し、LLM/GCP 非依存に
    authoring_loop（作成→レビュー→ゲートの巡回・再作成）→finalize の結合（順序・早期終了・
    再作成・確定/HITLフラグ）を検証する（§16）。root_agent（agent.py）は引数なしで呼ぶため本番挙動は不変。

    `after_agent_callback`＝`persist_visit_to_memory`：全段の後に1度、保育士の明示承認
    （caregiver_approved=True）＋型成立のときだけ来園を Memory Bank へ書き戻す（真の承認ゲート＝§9/§13）。
    memory_service 未配線・未承認でも降格/保留するため、注入の有無で順序制御や既存挙動は変わらない。

    文書作成指針は author/reviewer の InstructionProvider（`agents/instructions.py`）が prompt 冒頭へ
    決定的に注入する（§5）。パイプラインに prep 段は置かない（author が最初の LLM 段）。
    """
    return SequentialAgent(
        name="document_pipeline",
        sub_agents=[
            build_authoring_loop(build_author_agent(author_model), reviewer_model),
            FinalizeAgent(name="finalize"),
        ],
        after_agent_callback=persist_visit_to_memory,
    )
