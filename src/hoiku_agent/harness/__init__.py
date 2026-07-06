"""harness：決定的「型の保証」層の公開 API。

設計コンテキスト §5。決定的ロジックの "実体" はこの層に1つだけ置く。LlmAgent からは
tools/ の薄いラッパ（FunctionTool）経由で呼ぶ（二重実装しない）。LLM はここでは呼ばない。
"""

from .aggregate import (
    aggregate_by_child,
    child_record_digest,
    format_digest_for_prompt,
    format_record_digest_for_prompt,
    prev_month_digest,
)
from .draft import (
    write_child_record_draft,
    write_class_monthly_draft,
    write_draft,
    write_monthly_draft,
    write_nursery_record_draft,
)
from .finalize import (
    FinalizedDocument,
    finalize_child_record_document,
    finalize_class_monthly_document,
    finalize_document,
    finalize_monthly_document,
    finalize_nursery_record_document,
    parse_draft_to_child_record,
    parse_draft_to_class_plan,
    parse_draft_to_entry,
    parse_draft_to_nursery_record,
    parse_draft_to_plan,
)
from .policy_store import (
    active_cards,
    add_card,
    book_view,
    card_view,
    find_card,
    find_exact_duplicate,
    history_view,
    load_book,
    next_card_id,
    remove_card,
    render_to_text,
    save_book,
    store_status,
    supersede_card,
)
from .schema_check import (
    validate_child_record_fields,
    validate_class_monthly_fields,
    validate_fields,
    validate_monthly_fields,
    validate_nursery_record_fields,
)

# pipeline は agents → tools を芋づる式に読み込むため最後に import する
# （tools 側の薄いラッパは上記の実体を submodule 直参照しており、循環は回避済み）。
# router は各パイプライン（月案＝monthly / クラス月案＝class_monthly / 保育経過記録 / 要録）を束ねるため
# 各パイプラインの後に置く（保育日誌は AI 生成を退役＝ルータに載せない。pipeline.py は共用機構のみ）。
from .pipeline import CAREGIVER_APPROVAL_KEY, mark_caregiver_approved
from .monthly import build_monthly_pipeline
from .class_monthly import build_class_monthly_pipeline
from .child_record import build_child_record_pipeline
from .youroku import build_nursery_record_pipeline
from .router import build_root_agent

__all__ = [
    "build_monthly_pipeline",
    "build_class_monthly_pipeline",
    "build_child_record_pipeline",
    "build_nursery_record_pipeline",
    "build_root_agent",
    "mark_caregiver_approved",
    "CAREGIVER_APPROVAL_KEY",
    "validate_fields",
    "validate_monthly_fields",
    "validate_class_monthly_fields",
    "validate_child_record_fields",
    "validate_nursery_record_fields",
    "write_draft",
    "write_monthly_draft",
    "write_class_monthly_draft",
    "write_child_record_draft",
    "write_nursery_record_draft",
    "finalize_document",
    "finalize_monthly_document",
    "finalize_class_monthly_document",
    "finalize_child_record_document",
    "finalize_nursery_record_document",
    "parse_draft_to_entry",
    "parse_draft_to_plan",
    "parse_draft_to_class_plan",
    "parse_draft_to_child_record",
    "parse_draft_to_nursery_record",
    "FinalizedDocument",
    "aggregate_by_child",
    "prev_month_digest",
    "format_digest_for_prompt",
    "child_record_digest",
    "format_record_digest_for_prompt",
    # 育つ指針＝構造化カードストア（§8/§9）
    "load_book",
    "save_book",
    "add_card",
    "supersede_card",
    "remove_card",
    "render_to_text",
    "active_cards",
    "find_card",
    "next_card_id",
    "find_exact_duplicate",
    "store_status",
    "card_view",
    "history_view",
    "book_view",
]
