"""育つ「文書作成指針」ツール。

`プロダクト方針.md` §4 / 「回す」の本体。先輩の勘所・園のルール・現場の修正を
吸収して改善し続ける指針を読み書きする。作成AIは作成前にこれを参照し、レビューAIは
これを評価基準に使う。

MVP は `knowledge/文書作成指針.md` を読む。追記（学習）は HITL（人の確認）を挟む。

TODO(設計):
- 追記時の「矛盾検出→すり合わせ」フロー（プロダクト方針 §4）
- Agent Engine Memory Bank と接続し、園・担任ごとに指針を個別化
"""

from __future__ import annotations

from pathlib import Path

_GUIDELINE_PATH = Path(__file__).resolve().parents[3] / "knowledge" / "文書作成指針.md"


def load_writing_guideline() -> str:
    """現在の文書作成指針（現場の勘所の集積）を返す。"""
    if _GUIDELINE_PATH.exists():
        return _GUIDELINE_PATH.read_text(encoding="utf-8")
    return "（文書作成指針は未整備）"


def propose_guideline_update(advice: str) -> dict:
    """保育士のアドバイスを指針へ反映する提案を作る（実反映は HITL 承認後）。

    Args:
        advice: 「もっとこうしたい」等の現場の声。

    Returns:
        {"proposed": ..., "conflicts": [...]} 形式の提案。
    """
    # TODO: 既存指針との矛盾検出とすり合わせ。承認後に追記して「1周」を閉じる。
    return {"proposed": advice, "conflicts": []}
