from datetime import UTC, datetime
from decimal import Decimal

import pytest

from blue_wren.application.exporting import assess_checked_export
from blue_wren.application.review import (
    create_finding_history,
    mark_source_version_stale,
    record_review_decision,
)
from blue_wren.domain.exporting import ExportBlockerCode
from blue_wren.domain.findings import EvidenceReference, Finding, FindingStatus
from blue_wren.domain.review import FindingHistory, ReviewOutcome

NOW = datetime(2026, 9, 15, 2, 0, tzinfo=UTC)


def history(
    finding_id: str = "finding-revenue",
    *,
    status: FindingStatus = FindingStatus.PROPOSED,
) -> FindingHistory:
    finding = Finding(
        metric="revenue",
        actual=Decimal("125.0"),
        baseline=Decimal("120.0"),
        delta=Decimal("5.0") if status is FindingStatus.PROPOSED else None,
        unit="AUD_millions",
        period="2026-Q2",
        basis="reported",
        evidence=EvidenceReference(
            document_id="acme-q2-results",
            document_version_id="acme-q2-results:version-1",
            locator="page=2;table=results;row=revenue",
        ),
        status=status,
        reason="period_mismatch" if status is FindingStatus.UNRESOLVED else None,
    )
    return create_finding_history(finding_id, finding, NOW)


def reviewed(outcome: ReviewOutcome = ReviewOutcome.ACCEPTED) -> FindingHistory:
    return record_review_decision(
        history(),
        expected_version=1,
        outcome=outcome,
        reviewer_id="analyst-7",
        decided_at=NOW,
    )


def test_checked_export_allows_only_accepted_supported_findings() -> None:
    report = assess_checked_export((reviewed(),))

    assert report.allowed is True
    assert report.blockers == ()


@pytest.mark.parametrize(
    ("outcome", "code"),
    [
        (ReviewOutcome.PENDING, ExportBlockerCode.REVIEW_PENDING),
        (ReviewOutcome.REJECTED, ExportBlockerCode.REVIEW_REJECTED),
        (ReviewOutcome.DEFERRED, ExportBlockerCode.REVIEW_DEFERRED),
    ],
)
def test_checked_export_blocks_unaccepted_review_states(
    outcome: ReviewOutcome,
    code: ExportBlockerCode,
) -> None:
    candidate = history() if outcome is ReviewOutcome.PENDING else reviewed(outcome)

    report = assess_checked_export((candidate,))

    assert report.allowed is False
    assert report.blockers[0].finding_id == "finding-revenue"
    assert report.blockers[0].code is code


def test_checked_export_blocks_a_stale_approval() -> None:
    candidate = mark_source_version_stale(
        reviewed(),
        expected_version=1,
        document_id="acme-q2-results",
        superseding_version_id="acme-q2-results:version-2",
        marked_at=NOW,
    )

    report = assess_checked_export((candidate,))

    assert report.allowed is False
    assert report.blockers[0].code is ExportBlockerCode.STALE


def test_unresolved_finding_cannot_enter_checked_export() -> None:
    report = assess_checked_export((history(status=FindingStatus.UNRESOLVED),))

    assert report.allowed is False
    assert report.blockers[0].code is ExportBlockerCode.UNRESOLVED
