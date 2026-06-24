"""ツール：過去の日誌/月案を検索（参照・連続性）。

設計コンテキスト §6 ツール表（search_records）。作成AIが前月連続性や過去の実践を参照するために
自分で取りに行く（Agentic RAG / tool-use ループ）。月⇄日の還流（L2）の入力にもなる。

TODO(設計):
- 過去記録の保存先と検索方式の確定（セッション state / Memory Bank / RAG のどれを引くか）。
- child_id・期間でのフィルタ。
"""

from __future__ import annotations


def search_records(query: str, child_id: str | None = None, top_k: int = 4) -> list[dict]:
    """過去の日誌/月案を検索する。

    Args:
        query: 検索クエリ。
        child_id: 指定があればその子の記録に絞る（0–2 個別前提）。
        top_k: 取得件数。

    Returns:
        ヒットした記録（{"source", "text"} のリスト）。
    """
    # TODO: 実データソースに接続する。
    return [{"source": "TODO: 過去記録(未接続)", "text": f"[stub] '{query}' の過去記録"}]
