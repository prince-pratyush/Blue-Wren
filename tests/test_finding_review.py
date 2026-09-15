from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from blue_wren.application.review import (
    create_finding_history,
    mark_source_version_stale,
    record_review_decision,
    revise_finding,
)
from blue_wren.domain.findings import EvidenceReference, Finding, FindingStatus
from blue_wren.domain.review import (
    ReviewConflict,
    ReviewOutcome,
    ReviewValidationError,
)

CREATED_AT = datetime(2026, 9, 15, 1, 0, tzinfo=UTC)
DECIDED_AT = datetime(2026, 9, 15, 1, 5, tzinfo=UTC)


def finding(*, status: FindingStatus = FindingStatus.PROPOSED) -> Finding:
    return Finding(
        metric="revenue",
        actual=Decimal("125.0"),
        baseline=Decimal("120.0"),
        delta=Decimal("5.0") if status is FindingStatus.PROPOSED else None,
        unit="AUD_millions",
        period="2026-Q2",
        evidence=EvidenceReference(
            document_id="acme-q2-results",
            document_version_id="acme-q2-results:version-1",
            locator="page=2;table=results;row=revenue",
        ),
        status=status,
        reason="period_mismatch" if status is FindingStatus.UNRESOLVED else None,
    )


def test_create_finding_history_starts_with_one_pending_revision() -> None:
    history = create_finding_history(
        finding_id="finding-revenue",
        finding=finding(),
        created_at=CREATED_AT,
    )

    assert history.current_revision.version == 1
    assert history.current_outcome is ReviewOutcome.PENDING
    assert history.decisions == ()


def test_record_review_decision_retains_reviewer_time_and_version() -> None:
    history = create_finding_history("finding-revenue", finding(), CREATED_AT)

    reviewed = record_review_decision(
        history,
        expected_version=1,
        outcome=ReviewOutcome.ACCEPTED,
        reviewer_id="analyst-7",
        decided_at=DECIDED_AT,
        reason="Matches reported results",
    )

    decision = reviewed.decisions[0]
    assert decision.finding_version == 1
    assert decision.reviewer_id == "analyst-7"
    assert decision.decided_at == DECIDED_AT
    assert reviewed.current_outcome is ReviewOutcome.ACCEPTED


def test_revision_preserves_history_and_requires_fresh_review() -> None:
    history = create_finding_history("finding-revenue", finding(), CREATED_AT)
    reviewed = record_review_decision(
        history,
        expected_version=1,
        outcome=ReviewOutcome.ACCEPTED,
        reviewer_id="analyst-7",
        decided_at=DECIDED_AT,
    )
    revised_finding = replace(finding(), actual=Decimal("126.0"), delta=Decimal("6.0"))

    revised = revise_finding(
        reviewed,
        expected_version=1,
        finding=revised_finding,
        created_at=datetime(2026, 9, 15, 1, 10, tzinfo=UTC),
    )

    assert revised.current_revision.version == 2
    assert revised.current_revision.finding.actual == Decimal("126.0")
    assert revised.current_outcome is ReviewOutcome.PENDING
    assert revised.decisions == reviewed.decisions


def test_review_rejects_a_stale_expected_version() -> None:
    history = create_finding_history("finding-revenue", finding(), CREATED_AT)

    with pytest.raises(ReviewConflict, match="expected version 2, current version is 1"):
        record_review_decision(
            history,
            expected_version=2,
            outcome=ReviewOutcome.DEFERRED,
            reviewer_id="analyst-7",
            decided_at=DECIDED_AT,
        )


def test_unresolved_finding_cannot_be_accepted() -> None:
    history = create_finding_history(
        "finding-revenue",
        finding(status=FindingStatus.UNRESOLVED),
        CREATED_AT,
    )

    with pytest.raises(ReviewValidationError, match="unresolved finding cannot be accepted"):
        record_review_decision(
            history,
            expected_version=1,
            outcome=ReviewOutcome.ACCEPTED,
            reviewer_id="analyst-7",
            decided_at=DECIDED_AT,
        )


def test_review_decision_is_append_only_for_each_version() -> None:
    history = create_finding_history("finding-revenue", finding(), CREATED_AT)
    reviewed = record_review_decision(
        history,
        expected_version=1,
        outcome=ReviewOutcome.REJECTED,
        reviewer_id="analyst-7",
        decided_at=DECIDED_AT,
    )

    with pytest.raises(ReviewConflict, match="finding version 1 is already reviewed"):
        record_review_decision(
            reviewed,
            expected_version=1,
            outcome=ReviewOutcome.ACCEPTED,
            reviewer_id="analyst-8",
            decided_at=DECIDED_AT,
        )


def test_pending_cannot_be_recorded_as_a_decision() -> None:
    history = create_finding_history("finding-revenue", finding(), CREATED_AT)

    with pytest.raises(ReviewValidationError, match="pending is not a review decision"):
        record_review_decision(
            history,
            expected_version=1,
            outcome=ReviewOutcome.PENDING,
            reviewer_id="analyst-7",
            decided_at=DECIDED_AT,
        )


@pytest.mark.parametrize(
    ("finding_id", "created_at", "message"),
    [
        (" ", CREATED_AT, "finding_id is required"),
        ("finding-revenue", datetime(2026, 9, 15, 1, 0), "timestamp must include a timezone"),
    ],
)
def test_history_requires_identity_and_unambiguous_time(
    finding_id: str,
    created_at: datetime,
    message: str,
) -> None:
    with pytest.raises(ReviewValidationError, match=message):
        create_finding_history(finding_id, finding(), created_at)


def test_new_source_version_stales_an_accepted_finding() -> None:
    history = create_finding_history("finding-revenue", finding(), CREATED_AT)
    reviewed = record_review_decision(
        history,
        expected_version=1,
        outcome=ReviewOutcome.ACCEPTED,
        reviewer_id="analyst-7",
        decided_at=DECIDED_AT,
    )

    stale = mark_source_version_stale(
        reviewed,
        expected_version=1,
        document_id="acme-q2-results",
        superseding_version_id="acme-q2-results:version-2",
        marked_at=datetime(2026, 9, 15, 1, 15, tzinfo=UTC),
    )

    assert stale.current_outcome is ReviewOutcome.STALE
    assert stale.decisions == reviewed.decisions
    assert stale.staleness[0].superseded_version_id == "acme-q2-results:version-1"
    assert stale.staleness[0].superseding_version_id == "acme-q2-results:version-2"


def test_source_change_only_stales_dependent_findings() -> None:
    history = create_finding_history("finding-revenue", finding(), CREATED_AT)

    unchanged = mark_source_version_stale(
        history,
        expected_version=1,
        document_id="different-document",
        superseding_version_id="different-document:version-2",
        marked_at=DECIDED_AT,
    )

    assert unchanged is history
    assert unchanged.current_outcome is ReviewOutcome.PENDING


def test_current_source_version_does_not_stale_a_finding() -> None:
    history = create_finding_history("finding-revenue", finding(), CREATED_AT)

    unchanged = mark_source_version_stale(
        history,
        expected_version=1,
        document_id="acme-q2-results",
        superseding_version_id="acme-q2-results:version-1",
        marked_at=DECIDED_AT,
    )

    assert unchanged is history


def test_revising_a_stale_finding_requires_fresh_review() -> None:
    history = create_finding_history("finding-revenue", finding(), CREATED_AT)
    stale = mark_source_version_stale(
        history,
        expected_version=1,
        document_id="acme-q2-results",
        superseding_version_id="acme-q2-results:version-2",
        marked_at=DECIDED_AT,
    )
    revised_finding = replace(
        finding(),
        evidence=replace(
            finding().evidence,
            document_version_id="acme-q2-results:version-2",
        ),
    )

    revised = revise_finding(
        stale,
        expected_version=1,
        finding=revised_finding,
        created_at=datetime(2026, 9, 15, 1, 20, tzinfo=UTC),
    )

    assert revised.current_revision.version == 2
    assert revised.current_outcome is ReviewOutcome.PENDING
    assert len(revised.staleness) == 1


def test_repeated_staleness_event_is_idempotent() -> None:
    history = create_finding_history("finding-revenue", finding(), CREATED_AT)
    stale = mark_source_version_stale(
        history,
        expected_version=1,
        document_id="acme-q2-results",
        superseding_version_id="acme-q2-results:version-2",
        marked_at=DECIDED_AT,
    )

    repeated = mark_source_version_stale(
        stale,
        expected_version=1,
        document_id="acme-q2-results",
        superseding_version_id="acme-q2-results:version-2",
        marked_at=DECIDED_AT,
    )

    assert repeated is stale
    assert len(repeated.staleness) == 1
