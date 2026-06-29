"""ツール：育つ「文書作成指針」を読む（構造化カードストア＝§8/§9）。

設計コンテキスト §6 ツール表（read_policy）/ §9。育つ指針＝メモリ②。作成AIは作成前にこれを参照し、
レビューAIは評価基準に使う。指針の正(SSOT)は構造化カード `knowledge/文書作成指針.json` で、改善エージェント
（improver/）が意味的競合を精査し保育士の決定で即反映する（読みと書きを分離：ここは読み取り専用）。

本ツールは active カードから人間/LLM 可読テキストを `harness.policy_store.render_to_text` で再生して返す
（旧 markdown と同じ節構成）。ストア未整備/壊れは「未整備」へ降格する（偽の中身を出さない）。
"""

from __future__ import annotations

from ..harness.policy_store import load_book, render_to_text


def read_policy() -> str:
    """現在の文書作成指針（現場の勘所の集積）を返す。"""
    try:
        text = render_to_text(load_book())
    except Exception:  # noqa: BLE001  ストア未整備/壊れは降格（ライブ生成を落とさない）
        return "（文書作成指針は未整備）"
    return text or "（文書作成指針は未整備）"
