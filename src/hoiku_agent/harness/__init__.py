"""harness：決定的「型の保証」層の公開 API。

設計コンテキスト §5。決定的ロジックの "実体" はこの層に1つだけ置く。LlmAgent からは
tools/ の薄いラッパ（FunctionTool）経由で呼ぶ（二重実装しない）。LLM はここでは呼ばない。
"""

from .aggregate import aggregate_by_child, format_digest_for_prompt, prev_month_digest
from .draft import write_draft, write_monthly_draft
from .finalize import (
    FinalizedDocument,
    finalize_document,
    finalize_monthly_document,
    parse_draft_to_entry,
    parse_draft_to_plan,
)
from .git_ops import StructuredEdit, apply_structured_edit, list_section_bullets, open_pr
from .schema_check import validate_fields, validate_monthly_fields

# pipeline は agents → tools を芋づる式に読み込むため最後に import する
# （tools 側の薄いラッパは上記の実体を submodule 直参照しており、循環は回避済み）。
# router は両パイプライン（日誌＝pipeline / 月案＝monthly）を束ねるため pipeline/monthly の後に置く。
from .pipeline import build_document_pipeline
from .monthly import build_monthly_pipeline
from .router import build_root_agent

__all__ = [
    "build_document_pipeline",
    "build_monthly_pipeline",
    "build_root_agent",
    "validate_fields",
    "validate_monthly_fields",
    "write_draft",
    "write_monthly_draft",
    "finalize_document",
    "finalize_monthly_document",
    "parse_draft_to_entry",
    "parse_draft_to_plan",
    "FinalizedDocument",
    "aggregate_by_child",
    "prev_month_digest",
    "format_digest_for_prompt",
    "apply_structured_edit",
    "list_section_bullets",
    "open_pr",
    "StructuredEdit",
]
