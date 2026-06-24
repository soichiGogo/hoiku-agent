"""ツール：様式に整形してドラフト出力（harness への薄いラッパ）。

設計コンテキスト §5/§6。**実体は harness/draft.py に1つだけ**。ここはそれを FunctionTool として
渡すための薄いラッパで、ロジックを再実装しない（二重実装禁止＝§5）。なお最終の整形済みドラフトの
確定出力は harness がパイプライン末尾で決定的に実行する（tool ではなくステップ＝§6）。
"""

from __future__ import annotations

# 実体モジュールを直接参照する（harness パッケージ __init__ 経由だと
# harness.pipeline → agents → tools → ここ の循環 import に巻き込まれるため）。
from ..harness.draft import write_draft as _write_draft
from ..schemas import DiaryEntry


def write_draft(entry: DiaryEntry, template_ref: str | None = None) -> str:
    """日誌ドラフト（DiaryEntry）を様式テキストへ整形して返す。"""
    return _write_draft(entry, template_ref=template_ref)
