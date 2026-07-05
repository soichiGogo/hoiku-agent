"""作成AI・レビューAIの動的 instruction（InstructionProvider）＝文書作成指針・集積の前置注入。

設計コンテキスト §5（決定的に用意できるものは harness）/ §6（作成AI）/ §8・§9（育つ指針）。

doc_type は router で確定済み＝どの指針が要るかも確定済みなので、文書作成指針の "提示" は harness が
決定的に用意する（探索を LLM の自発的な read_policy 呼び出しに委ねない＝旧 read_policy ツールは撤去）。
本モジュールは author/reviewer の `instruction` を **callable（ADK の InstructionProvider）** にし、
prompt の冒頭へ「この書類に適用する文書作成指針（共通＋当該書類の勘所）」と「踏まえる集積（月案＝前月
L2／児童票＝期間 L3）」を決定的に差し込む。これにより作成/レビューAI は指針を**与件**として動き始める
（前提理解 → 情報収集 → 文書作成の流れ）。

責務境界：ここは prompt 文字列の**組み立て（presentation）**だけを行い、指針テキストの再生
（`harness.policy_store.render_for_doc`）と集積の整形（`harness.aggregate.format_digest_for_prompt`）
という決定ロジックの実体は harness に置く（tools/ が harness を呼ぶ薄いラッパなのと同じ流儀＝§5）。
ストア未整備/障害は「指針なし」へ降格して素通りする（偽の中身を出さない・生成を止めない＝§9）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from ..harness.aggregate import format_digest_for_prompt
from ..harness.policy_store import load_book, render_for_doc
from ..schemas.policy import PolicyScope

if TYPE_CHECKING:
    from google.adk.agents.readonly_context import ReadonlyContext

# state["doc_type"] → (指針 scope, 集積の state キー, 集積の見出しラベル)。
# 集積を持たない日誌は digest_key=None。router の doc_type 値（保育日誌/月案/児童票）に一致させる。
_DOC_TYPE_ROUTING: dict[str, tuple[PolicyScope, str | None, str]] = {
    "保育日誌": (PolicyScope.保育日誌, None, ""),
    "月案": (PolicyScope.月案, "prev_month_digest", "前月"),
    "児童票": (PolicyScope.児童票, "period_digest", "期間"),
}
# doc_type 未設定時の既定（router の既定＝保育日誌＝§3）。
_DEFAULT_ROUTING = _DOC_TYPE_ROUTING["保育日誌"]


def _policy_text(scope: PolicyScope) -> str:
    """作る書類（scope）向けの文書作成指針（共通＋当該書類）を再生する。障害は空へ降格（§9）。"""
    try:
        return render_for_doc(load_book(), scope) or ""
    except Exception:  # noqa: BLE001  ストア未整備/壊れ/障害は降格（生成を止めない）
        return ""


def _compose(base: str, scope: PolicyScope, state, digest_key: str | None, label: str) -> str:
    """指針（＋集積）を prompt 冒頭に前置し、base instruction を続ける（与件→手順の順）。"""
    parts: list[str] = []
    policy = _policy_text(scope)
    if policy:
        parts.append(policy)
    if digest_key:
        digest = state.get(digest_key)
        if digest:  # 空 digest（初回）は前置しない
            parts.append(format_digest_for_prompt(digest, label=label))
    parts.append(base)
    return "\n\n".join(parts)


def build_author_instruction(
    base: str, scope: PolicyScope, digest_key: str | None = None, digest_label: str = ""
) -> Callable[[ReadonlyContext], str]:
    """作成AI の InstructionProvider を作る（scope は書類ごとに確定＝factory 時に固定）。

    diary は digest_key=None（集積なし）／月案・児童票は state の digest（前月／期間）を前置する。
    """

    def provider(ctx: ReadonlyContext) -> str:
        return _compose(base, scope, ctx.state, digest_key, digest_label)

    return provider


def build_review_instruction(base: str) -> Callable[[ReadonlyContext], str]:
    """レビューAI（日誌/月案/児童票で共用）の InstructionProvider を作る。

    reviewer は書類共用なので scope・集積は runtime の state["doc_type"] から解決する
    （未設定は既定＝保育日誌）。作成AI と同じ指針・集積を評価基準として prompt 冒頭に前置する。
    """

    def provider(ctx: ReadonlyContext) -> str:
        scope, digest_key, label = _DOC_TYPE_ROUTING.get(
            ctx.state.get("doc_type"), _DEFAULT_ROUTING
        )
        return _compose(base, scope, ctx.state, digest_key, label)

    return provider
