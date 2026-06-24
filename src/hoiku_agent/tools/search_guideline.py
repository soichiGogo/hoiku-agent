"""ツール：保育所保育指針・10の姿を RAG 検索（静的ナレッジ）。

設計コンテキスト §6 ツール表 / §9。静的な参照知識（保育所保育指針解説・10の姿・3つの視点）は
Vertex RAG に置き、作成AIが「中身を決定」する際に自分で取りに行く（Agentic RAG）。

TODO(設計):
- Vertex RAG Engine の corpus（保育所保育指針・10の姿）を作成し RAG_CORPUS に設定（§11）。
- ADK の VertexAiRagRetrieval ツールへ置換、または本関数内から RAG API を呼ぶ。
"""

from __future__ import annotations


def search_guideline(query: str, top_k: int = 4) -> list[dict]:
    """保育所保育指針・10の姿などの静的ナレッジを検索する。

    Args:
        query: 検索クエリ（例「3歳児 言葉 ねらい」）。
        top_k: 取得件数。

    Returns:
        ヒットしたチャンク（{"source", "text"} のリスト）。
    """
    # TODO: Vertex RAG Engine 呼び出しに置き換える。
    return [
        {
            "source": "TODO: 保育所保育指針(RAG未接続)",
            "text": f"[stub] '{query}' に関する指針チャンクをここに返す",
        }
    ]
