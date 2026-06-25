"""ツール：子ども別の長期メモリを取得（Agent Engine Memory Bank）。

設計コンテキスト §6 ツール表（get_child_memory）/ §9。子ども別の長期メモリ＝メモリ①。
来園のたびに像が育つローリングな個別化（§13）。エージェントは Cloud Run 直ホストで、Memory Bank は
Agent Engine Runtime に載せ替えず、マネージドのメモリサービスとして呼ぶ（§9）。

配線（v0 確定）：ADK の MemoryService を Runner に設定した上で、ツールから
`tool_context.search_memory(query)`（async）で引く。MemoryService 実体は本番では
`VertexAiMemoryBankService`（config.agent_engine_id を Memory Bank として使用＝§9）。
**Runner に MemoryService が無い環境では search_memory が ValueError を投げる**ので、降格して
無害なフォールバックを返す（稼働中パイプラインを落とさない）。

接続 ID は config.agent_engine_id（用途は Memory Bank に限定。Runtime 名残と混同しない＝§9）。
"""

from __future__ import annotations

from google.adk.tools import ToolContext


def _content_text(entry: object) -> str:
    """MemoryEntry.content（genai Content）からテキストを連結して取り出す。"""
    content = getattr(entry, "content", None)
    parts = getattr(content, "parts", None) or []
    texts = [p.text for p in parts if getattr(p, "text", None)]
    return " ".join(texts).strip()


async def get_child_memory(
    child_id: str,
    query: str | None = None,
    tool_context: ToolContext | None = None,
) -> list[dict]:
    """子ども別の長期メモリ（その子の姿・発達の蓄積）を取得する。

    Args:
        child_id: 対象の子ども（架空児のみ＝§14）。
        query: 関連メモリの絞り込みクエリ（任意）。
        tool_context: ADK が注入（宣言には現れない）。MemoryService 経由の検索に使う。

    Returns:
        関連メモリ（{"text", ...} のリスト）。未接続時は降格メッセージ1件。
    """
    search = f"child_id={child_id}" + (f" {query}" if query else "")
    if tool_context is None:
        return [{"text": f"[memory未接続] child_id={child_id} の長期メモリは取得できません"}]
    try:
        response = await tool_context.search_memory(search)
    except ValueError:
        # Runner に MemoryService 未設定（ローカル/未接続）。降格。
        return [{"text": f"[memory未接続] child_id={child_id}（Memory Bank 未設定）"}]
    results = [
        {"text": text}
        for entry in (getattr(response, "memories", None) or [])
        if (text := _content_text(entry))
    ]
    return results or [{"text": f"child_id={child_id} に該当する長期メモリは見つかりませんでした"}]
