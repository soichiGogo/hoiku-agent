"""ツール集約：作成AIに渡す4–8個の鋭い汎用プリミティブ（設計コンテキスト §6）。

中核に DAG/分類器/RAG を詰め込まない。決定的ロジック（validate_fields/write_draft）の実体は
harness/ にあり、ここはそれを呼ぶ薄いラッパ（二重実装しない＝§5）。improver 固有のツール
（read_policy_cards/propose_policy_card/commit_policy_card）は improver/tools.py に分離する（一階の tools/ と混ぜない）。
"""

# ask_caregiver の公開シンボルは LongRunningFunctionTool インスタンス（HITL＝§6）。
from .ask_caregiver import ask_caregiver_tool as ask_caregiver
from .recall_child_history import recall_child_history
from .search_guideline import search_guideline
from .search_past_documents import search_past_documents
from .validate_fields import validate_fields
from .write_draft import write_draft

__all__ = [
    "search_past_documents",
    "search_guideline",
    "recall_child_history",
    "ask_caregiver",
    "validate_fields",
    "write_draft",
]
