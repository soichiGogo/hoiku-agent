"""ツール：必須欄の充足・年齢分岐チェック（harness への薄いラッパ）。

設計コンテキスト §5/§6。**実体は harness/schema_check.py に1つだけ**。ここはそれを FunctionTool
として author に渡すための薄いラッパで、ロジックを再実装しない（二重実装禁止＝§5）。author には
「生成途中の自己点検」に使わせる。最終の確定 validation は harness がパイプライン末尾で実行する。
"""

from __future__ import annotations

from ..harness import validate_fields as _validate_fields
from ..schemas import DiaryEntry


def validate_fields(entry: DiaryEntry) -> list[str]:
    """日誌ドラフトの必須欄・年齢分岐を検査し、違反メッセージの一覧を返す（空＝充足）。"""
    return _validate_fields(entry)
