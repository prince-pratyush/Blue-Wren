from dataclasses import replace
from datetime import datetime

from blue_wren.domain.findings import Finding, FindingStatus
from blue_wren.domain.review import (
    FindingHistory,
    FindingRevision,
    ReviewConflict,
    ReviewDecision,
    ReviewOutcome,
    ReviewValidationError,
)


def create_finding_history(
    finding_id: str,
    finding: Finding,
    created_at: datetime,
) -> FindingHistory:
    _require_identity(finding_id, "finding_id")
    _require_timezone(created_at)
    revision = FindingRevision(
        finding_id=finding_id,
        version=1,
        finding=finding,
        created_at=created_at,
    )
    return FindingHistory(revisions=(revision,), decisions=())


def record_review_decision(
    history: FindingHistory,
    *,
    expected_version: int,
    outcome: ReviewOutcome,
    reviewer_id: str,
    decided_at: datetime,
    reason: str | None = None,
) -> FindingHistory:
    current = history.current_revision
    _require_current_version(current.version, expected_version)
    _require_identity(reviewer_id, "reviewer_id")
    _require_timezone(decided_at)
    if outcome is ReviewOutcome.PENDING:
        raise ReviewValidationError("pending is not a review decision")
    if history.current_outcome is not ReviewOutcome.PENDING:
        raise ReviewConflict(f"finding version {current.version} is already reviewed")
    if (
        outcome is ReviewOutcome.ACCEPTED
        and current.finding.status is FindingStatus.UNRESOLVED
    ):
        raise ReviewValidationError("unresolved finding cannot be accepted")

    decision = ReviewDecision(
        finding_id=current.finding_id,
        finding_version=current.version,
        outcome=outcome,
        reviewer_id=reviewer_id,
        decided_at=decided_at,
        reason=reason,
    )
    return replace(history, decisions=(*history.decisions, decision))


def revise_finding(
    history: FindingHistory,
    *,
    expected_version: int,
    finding: Finding,
    created_at: datetime,
) -> FindingHistory:
    current = history.current_revision
    _require_current_version(current.version, expected_version)
    _require_timezone(created_at)
    revision = FindingRevision(
        finding_id=current.finding_id,
        version=current.version + 1,
        finding=finding,
        created_at=created_at,
    )
    return replace(history, revisions=(*history.revisions, revision))


def _require_current_version(current_version: int, expected_version: int) -> None:
    if current_version != expected_version:
        raise ReviewConflict(
            f"expected version {expected_version}, current version is {current_version}"
        )


def _require_identity(value: str, field: str) -> None:
    if not value.strip():
        raise ReviewValidationError(f"{field} is required")


def _require_timezone(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ReviewValidationError("timestamp must include a timezone")
