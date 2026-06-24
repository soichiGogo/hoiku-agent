"""harness：決定的「型の保証」層の公開 API。

設計コンテキスト §5。決定的ロジックの "実体" はこの層に1つだけ置く。LlmAgent からは
tools/ の薄いラッパ（FunctionTool）経由で呼ぶ（二重実装しない）。LLM はここでは呼ばない。
"""

from .aggregate import aggregate_by_child
from .draft import write_draft
from .git_ops import apply_structured_edit, open_pr
from .pipeline import build_document_pipeline
from .schema_check import validate_fields

__all__ = [
    "build_document_pipeline",
    "validate_fields",
    "write_draft",
    "aggregate_by_child",
    "apply_structured_edit",
    "open_pr",
]
