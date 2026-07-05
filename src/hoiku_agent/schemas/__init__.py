"""スキーマ集約。書類の要件・出力型・ドメイン定数を1箇所に集める（規約: schemas/ 集約）。"""

from .document import (
    ChildAttendance,
    ChildRecord,
    DevelopmentNote,
    DiaryEntry,
    DiaryEvaluation,
    DocumentSpec,
    DocumentType,
    IndividualNote,
    LifeRecord,
    MonthlyEducationNote,
    MonthlyPlan,
    NurseryRecord,
    ReviewCriteria,
    ReviewFinding,
)
from .domain import FiveDomains, TenNoSugata, ThreeViewpoint
from .enums import AgeBand, Certainty, Lineage
from .notation import NotationBook, NotationKind, NotationRule
from .policy import (
    PolicyBook,
    PolicyCard,
    PolicyChange,
    PolicyChangeAction,
    PolicyScope,
    PolicyStatus,
)

__all__ = [
    # document
    "DocumentType",
    "DocumentSpec",
    "ReviewCriteria",
    "ReviewFinding",
    "ChildAttendance",
    "IndividualNote",
    "LifeRecord",
    "DiaryEvaluation",
    "DiaryEntry",
    "MonthlyEducationNote",
    "MonthlyPlan",
    "DevelopmentNote",
    "ChildRecord",
    "NurseryRecord",
    # enums
    "AgeBand",
    "Lineage",
    "Certainty",
    # domain
    "FiveDomains",
    "ThreeViewpoint",
    "TenNoSugata",
    # policy（育つ指針＝構造化カード・§8/§9）
    "PolicyScope",
    "PolicyStatus",
    "PolicyChangeAction",
    "PolicyCard",
    "PolicyChange",
    "PolicyBook",
    # notation（ひらがな表記DX＝決定的な表記の統一・§5）
    "NotationKind",
    "NotationRule",
    "NotationBook",
]
