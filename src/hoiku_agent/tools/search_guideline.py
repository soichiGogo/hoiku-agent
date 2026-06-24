"""ナレッジ検索ツール（B独自DB）。

作成AIが「中身を決定」する際に自分で取りに行く情報源（プロダクト方針 §2 エージェント層）。
本実装は Vertex RAG Engine の corpus を引く想定のスタブ。まずはローカルの
`knowledge/` を引く簡易版でも可（設計フェーズで差し替え）。

TODO(設計):
- Vertex RAG Engine の corpus（保育所保育指針・10の姿）を作成し RAG_CORPUS に設定
- ADK の VertexAiRagRetrieval ツールへ置き換える、または本関数内から RAG API を呼ぶ
"""

from __future__ import annotations


def search_guideline(query: str, top_k: int = 4) -> list[dict]:
    """保育所保育指針・10の姿などの独自ナレッジDBを検索する。

    Args:
        query: 検索クエリ（例「3歳児 言葉 ねらい」）。
        top_k: 取得件数。

    Returns:
        ヒットしたチャンク（{"source", "text"} のリスト）。
    """
    # TODO: Vertex RAG Engine 呼び出しに置き換える
    return [
        {
            "source": "TODO: 保育所保育指針(RAG未接続)",
            "text": f"[stub] '{query}' に関する指針チャンクをここに返す",
        }
    ]
