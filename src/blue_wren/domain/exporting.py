from dataclasses import dataclass
from enum import StrEnum


class ExportBlockerCode(StrEnum):
    UNRESOLVED = "unresolved"
    STALE = "stale"
    REVIEW_PENDING = "review_pending"
    REVIEW_REJECTED = "review_rejected"
    REVIEW_DEFERRED = "review_deferred"
    CITATION_UNRESOLVED = "citation_unresolved"


@dataclass(frozen=True, slots=True)
class ExportBlocker:
    finding_id: str
    code: ExportBlockerCode


@dataclass(frozen=True, slots=True)
class CheckedExportReadiness:
    allowed: bool
    blockers: tuple[ExportBlocker, ...]
