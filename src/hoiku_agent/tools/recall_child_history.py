"""ツール：その子の前回までの姿・育ちの蓄積を取得（Agent Engine Memory Bank）。

設計コンテキスト §6 ツール表 / §9。子ども別の長期メモリ＝メモリ①。来園のたびに像が育つ
ローリングな個別化（§13）。**「同じ子の継続性（前回までの様子・発達の流れ）」を踏まえたいときは
必ずこのツールを引く**。過去に作成した書類の本文そのものは `search_past_documents`（用途が違う）。

エージェントは Cloud Run 直ホストで、Memory Bank は Agent Engine Runtime に載せ替えず、マネージドの
メモリサービスとして呼ぶ（§9）。

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


async def recall_child_history(
    child_id: str,
    query: str | None = None,
    tool_context: ToolContext | None = None,
) -> list[dict]:
    """その子の前回までの姿・育ちの蓄積（来園横断の像）を取得する。

    同じ子の継続性（前回までの様子・発達の流れ）を踏まえたいときは必ずこれを引く。過去の生の
    書類本文ではなく、Memory Bank が来園を跨いで統合した「その子の像」を返す。

    Args:
        child_id: 対象の子ども（架空児のみ＝§14）。
        query: 関連メモリの絞り込みクエリ（任意）。
        tool_context: ADK が注入（宣言には現れない）。MemoryService 経由の検索に使う。

    Returns:
        その子の関連メモリ（{"text", ...} のリスト）。未接続時は降格メッセージ1件。
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
