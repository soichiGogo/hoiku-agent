"""harness：決定的「型の保証」層の公開 API。

設計コンテキスト §5。決定的ロジックの "実体" はこの層に1つだけ置く。LlmAgent からは
tools/ の薄いラッパ（FunctionTool）経由で呼ぶ（二重実装しない）。LLM はここでは呼ばない。
"""

from .aggregate import aggregate_by_child
from .draft import write_draft
from .finalize import FinalizedDocument, finalize_document, parse_draft_to_entry
from .git_ops import StructuredEdit, apply_structured_edit, list_section_bullets, open_pr
from .schema_check import validate_fields

# pipeline は agents → tools を芋づる式に読み込むため最後に import する
# （tools 側の薄いラッパは上記の実体を submodule 直参照しており、循環は回避済み）。
from .pipeline import build_document_pipeline

__all__ = [
    "build_document_pipeline",
    "validate_fields",
    "write_draft",
    "finalize_document",
    "parse_draft_to_entry",
    "FinalizedDocument",
    "aggregate_by_child",
    "apply_structured_edit",
    "list_section_bullets",
    "open_pr",
    "StructuredEdit",
]
