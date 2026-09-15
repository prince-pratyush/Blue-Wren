from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from blue_wren.domain.findings import Finding


class ReviewOutcome(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    DEFERRED = "deferred"


class ReviewConflict(ValueError):
    pass


class ReviewValidationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class FindingRevision:
    finding_id: str
    version: int
    finding: Finding
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ReviewDecision:
    finding_id: str
    finding_version: int
    outcome: ReviewOutcome
    reviewer_id: str
    decided_at: datetime
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class FindingHistory:
    revisions: tuple[FindingRevision, ...]
    decisions: tuple[ReviewDecision, ...]

    @property
    def current_revision(self) -> FindingRevision:
        return self.revisions[-1]

    @property
    def current_outcome(self) -> ReviewOutcome:
        current_version = self.current_revision.version
        return next(
            (
                decision.outcome
                for decision in reversed(self.decisions)
                if decision.finding_version == current_version
            ),
            ReviewOutcome.PENDING,
        )
