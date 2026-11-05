from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
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


class ExportBlocked(ValueError):
    def __init__(self, blockers: tuple[ExportBlocker, ...]) -> None:
        super().__init__("export blocked")
        self.blockers = blockers


@dataclass(frozen=True, slots=True)
class ExportedSource:
    document_id: str
    document_version_id: str
    content_sha256: str
    source_name: str
    published_at: datetime
    available_at: datetime


@dataclass(frozen=True, slots=True)
class ExportedFinding:
    finding_id: str
    version: int
    metric: str
    actual: Decimal
    baseline: Decimal
    delta: Decimal
    unit: str
    period: str
    basis: str
    baseline_target: str
    reviewer_id: str
    decided_at: datetime
    document_id: str
    document_version_id: str
    locator: str
    evidence_text: str


@dataclass(frozen=True, slots=True)
class ExportManifest:
    event_id: str
    company_id: str
    revision: int
    generated_at: datetime
    findings: tuple[ExportedFinding, ...]
    sources: tuple[ExportedSource, ...]
