from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from blue_wren.application.event_review import (
    EventReviewError,
    decide_event_finding,
    start_event_review,
)
from blue_wren.application.exporting import assess_checked_export
from blue_wren.application.replay import replay_event_fixture
from blue_wren.domain.findings import EventReplayResult
from blue_wren.domain.review import ReviewOutcome

FIXTURE = Path(__file__).parent / "fixtures" / "acme_q2_2026.json"
NOW = datetime(2026, 9, 15, 3, 0, tzinfo=UTC)


def test_start_event_review_assigns_stable_finding_identities() -> None:
    replay = replay_event_fixture(FIXTURE)

    first = start_event_review(replay, created_at=NOW)
    second = start_event_review(replay, created_at=NOW)

    assert first.event_id == "acme-q2-2026"
    assert first.company_id == "ACME-AU"
    assert len(first.findings) == 1
    assert first.findings[0].current_revision.finding_id == (
        second.findings[0].current_revision.finding_id
    )


def test_decide_event_finding_completes_checked_export_path() -> None:
    session = start_event_review(replay_event_fixture(FIXTURE), created_at=NOW)
    finding_id = session.findings[0].current_revision.finding_id

    reviewed = decide_event_finding(
        session,
        finding_id=finding_id,
        expected_version=1,
        outcome=ReviewOutcome.ACCEPTED,
        reviewer_id="analyst-7",
        decided_at=NOW,
    )

    assert reviewed.findings[0].current_outcome is ReviewOutcome.ACCEPTED
    assert assess_checked_export(reviewed.findings).allowed is True


def test_decide_event_finding_changes_only_the_selected_finding() -> None:
    replay = replay_event_fixture(FIXTURE)
    revenue = replay.findings[0]
    ebitda = replace(revenue, metric="ebitda")
    multi_finding_replay = EventReplayResult(
        event_id=replay.event_id,
        company_id=replay.company_id,
        findings=(revenue, ebitda),
    )
    session = start_event_review(multi_finding_replay, created_at=NOW)
    finding_id = session.findings[0].current_revision.finding_id

    reviewed = decide_event_finding(
        session,
        finding_id=finding_id,
        expected_version=1,
        outcome=ReviewOutcome.ACCEPTED,
        reviewer_id="analyst-7",
        decided_at=NOW,
    )

    assert reviewed.findings[0].current_outcome is ReviewOutcome.ACCEPTED
    assert reviewed.findings[1].current_outcome is ReviewOutcome.PENDING
    assert (
        reviewed.findings[1].current_revision.finding_id
        == session.findings[1].current_revision.finding_id
    )


def test_decide_event_finding_rejects_an_unknown_identity() -> None:
    session = start_event_review(replay_event_fixture(FIXTURE), created_at=NOW)

    with pytest.raises(EventReviewError, match="finding not found: missing"):
        decide_event_finding(
            session,
            finding_id="missing",
            expected_version=1,
            outcome=ReviewOutcome.ACCEPTED,
            reviewer_id="analyst-7",
            decided_at=NOW,
        )


def test_start_event_review_rejects_duplicate_finding_identity() -> None:
    replay = replay_event_fixture(FIXTURE)
    duplicate_replay = replace(replay, findings=(replay.findings[0], replay.findings[0]))

    with pytest.raises(EventReviewError, match="duplicate finding identity"):
        start_event_review(duplicate_replay, created_at=NOW)
