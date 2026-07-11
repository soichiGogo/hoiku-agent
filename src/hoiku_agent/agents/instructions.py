"""作成/レビューAIへ育つ指針・既定参照・取得実績を注入する InstructionProvider。"""

from __future__ import annotations

from collections.abc import Callable

from google.adk.agents.readonly_context import ReadonlyContext

from ..harness.policy_store import load_book, render_for_doc
from ..schemas.policy import PolicyScope

_DOC_TYPE_SCOPE = {
    "保育日誌": PolicyScope.保育日誌,
    "月案": PolicyScope.月案,
    "クラス月案": PolicyScope.月案,
    "保育経過記録": PolicyScope.保育経過記録,
    "保育要録": PolicyScope.保育要録,
}


def _policy_text(scope: PolicyScope) -> str:
    try:
        return render_for_doc(load_book(), scope) or ""
    except Exception:  # noqa: BLE001 指針ストア障害は生成を止めず降格する
        return ""


def _manifest_text(state) -> str:
    rows = state.get("reference_manifest") or []
    if not rows:
        return "【参照取得実績】まだ fetch_reference による取得はありません。"
    lines = ["【参照取得実績】"]
    for row in rows:
        status = "データなし" if row.get("empty") else f"{row.get('count', 0)}件"
        lines.append(f"- {row.get('source', '')}: {status}")
    return "\n".join(lines)


def build_author_instruction(base: str, scope: PolicyScope) -> Callable[[ReadonlyContext], str]:
    """scope 固定の author provider。参照本文は注入せず、既定リストと取得指示だけを渡す。"""

    def provider(ctx: ReadonlyContext) -> str:
        return "\n\n".join(part for part in (_policy_text(scope), base) if part)

    return provider


def build_review_instruction(base: str) -> Callable[[ReadonlyContext], str]:
    """runtime doc_type の指針と author の参照 manifest を reviewer に渡す。"""

    def provider(ctx: ReadonlyContext) -> str:
        doc_type = (ctx.state.get("doc_type") or "").strip()
        scope = _DOC_TYPE_SCOPE.get(doc_type, PolicyScope.月案)
        return "\n\n".join((_policy_text(scope), _manifest_text(ctx.state), base))

    return provider
