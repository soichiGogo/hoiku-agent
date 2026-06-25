"""ツール：保育所保育指針・10の姿を RAG 検索（静的ナレッジ）。

設計コンテキスト §6 ツール表 / §9。静的な参照知識（保育所保育指針解説・10の姿・3つの視点）は
Vertex RAG に置き、作成AIが「中身を決定」する際に自分で取りに行く（Agentic RAG）。

配線（v0）：config.rag_corpus が設定されていれば Vertex RAG Engine（`vertexai.rag`）へ問い合わせる。
未設定・呼び出し失敗時は降格して無害なフォールバックを返す（稼働中パイプラインを落とさない）。
RAG corpus の作成と接続 ID 設定は層A の準備事項（§11/§18）。vertexai.rag の正確な API はバージョン差が
あるため、取得は防御的に行い、差異は降格で吸収する。
"""

from __future__ import annotations

from ..config import settings


def _fallback(query: str, reason: str) -> list[dict]:
    return [
        {
            "source": f"RAG未接続（{reason}）",
            "text": (
                f"'{query}' に対する保育所保育指針チャンクは取得できませんでした。"
                "config.rag_corpus を設定すると Vertex RAG から取得します（§9/§11）。"
            ),
        }
    ]


def search_guideline(query: str, top_k: int = 4) -> list[dict]:
    """保育所保育指針・10の姿などの静的ナレッジを検索する。

    Args:
        query: 検索クエリ（例「3歳児 言葉 ねらい」）。
        top_k: 取得件数。

    Returns:
        ヒットしたチャンク（{"source", "text"} のリスト）。未接続時は降格メッセージ1件。
    """
    if not settings.rag_corpus:
        return _fallback(query, "config.rag_corpus 未設定")
    try:
        import vertexai
        from vertexai import rag

        vertexai.init(
            project=settings.google_cloud_project or None,
            location=settings.google_cloud_location or None,
        )
        response = rag.retrieval_query(
            rag_resources=[rag.RagResource(rag_corpus=settings.rag_corpus)],
            text=query,
            rag_retrieval_config=rag.RagRetrievalConfig(top_k=top_k),
        )
        contexts = getattr(getattr(response, "contexts", None), "contexts", None) or []
        results = [
            {
                "source": getattr(c, "source_uri", None) or "保育所保育指針(RAG)",
                "text": getattr(c, "text", "") or "",
            }
            for c in contexts
            if getattr(c, "text", "")
        ]
        return results or _fallback(query, "該当チャンクなし")
    except Exception as e:  # noqa: BLE001  RAG 周りの広範な例外は降格で吸収（稼働を止めない）
        return _fallback(query, f"RAG 呼び出し失敗: {type(e).__name__}")
