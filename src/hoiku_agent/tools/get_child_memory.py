"""ツール：子ども別の長期メモリを取得（Agent Engine Memory Bank）。

設計コンテキスト §6 ツール表（get_child_memory）/ §9。子ども別の長期メモリ＝メモリ①。
来園のたびに像が育つローリングな個別化（§13）。エージェントは Cloud Run 直ホストで、Memory Bank は
Agent Engine Runtime に載せ替えず、マネージドのメモリサービスとして呼ぶ（§9）。

TODO(設計):
- ADK の MemoryService（VertexAiMemoryBankService）を本関数から使う配線（公式 docs で要確認＝§18）。
- 接続 ID は config.agent_engine_id（用途は Memory Bank に限定。Runtime 名残と混同しない＝§9）。
"""

from __future__ import annotations


def get_child_memory(child_id: str, query: str | None = None) -> list[dict]:
    """子ども別の長期メモリ（その子の姿・発達の蓄積）を取得する。

    Args:
        child_id: 対象の子ども（架空児のみ＝§14）。
        query: 関連メモリの絞り込みクエリ（任意）。

    Returns:
        関連メモリ（{"text", ...} のリスト）。
    """
    # TODO: VertexAiMemoryBankService に接続する。
    return [{"text": f"[stub] child_id={child_id} の長期メモリ（Memory Bank 未接続）"}]
