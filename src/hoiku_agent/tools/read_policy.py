"""ツール：育つ「文書作成指針」を読む（git ファイル・HEAD 参照）。

設計コンテキスト §6 ツール表（read_policy）/ §9。育つ指針＝メモリ②（git ファイル）。
作成AIは作成前にこれを参照し、レビューAIは評価基準に使う。**HEAD を参照**する（履歴は人が見る
証拠と eval 再生に使い、ライブ生成には注入しない＝§9）。指針の更新は improver/ が構造化編集で
提案し、HITL＋評価ゲートを経て取り込む（読みと書きを分離：ここは読み取り専用）。

v0 は working tree の `knowledge/文書作成指針.md` を読む（improver の更新は PR 経由なので
取り込み後は HEAD と一致する）。
"""

from __future__ import annotations

from pathlib import Path

_GUIDELINE_PATH = Path(__file__).resolve().parents[3] / "knowledge" / "文書作成指針.md"


def read_policy() -> str:
    """現在の文書作成指針（現場の勘所の集積）を返す。"""
    if _GUIDELINE_PATH.exists():
        return _GUIDELINE_PATH.read_text(encoding="utf-8")
    return "（文書作成指針は未整備）"
