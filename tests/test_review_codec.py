import json
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from blue_wren.application.event_review import decide_event_finding, start_event_review
from blue_wren.application.replay import replay_event, replay_event_fixture
from blue_wren.application.review import mark_source_version_stale, revise_finding
from blue_wren.application.review_codec import decode_session, encode_session
from blue_wren.domain.event_review import EventReviewSession
from blue_wren.domain.findings import (
    BaselineObservation,
    EvidenceReference,
    ReportedObservation,
)
from blue_wren.domain.review import ReviewOutcome

FIXTURE = Path(__file__).parent / "fixtures" / "acme_q2_2026.json"
NOW = datetime(2026, 9, 16, 1, 0, tzinfo=UTC)
SYDNEY = timezone(timedelta(hours=10))


def _rich_session() -> EventReviewSession:
    session = start_event_review(replay_event_fixture(FIXTURE), created_at=NOW)
    finding_id = session.findings[0].current_revision.finding_id
    session = decide_event_finding(
        session,
        finding_id=finding_id,
        expected_version=1,
        outcome=ReviewOutcome.ACCEPTED,
        reviewer_id="analyst-7",
        decided_at=NOW.astimezone(SYDNEY),
        reason="matches model",
    )
    history = mark_source_version_stale(
        session.findings[0],
        expected_version=1,
        document_id="acme-q2-results",
        superseding_version_id="acme-q2-results:version-2",
        marked_at=NOW + timedelta(hours=1),
    )
    history = revise_finding(
        history,
        expected_version=1,
        finding=history.current_revision.finding,
        created_at=NOW + timedelta(hours=2),
    )
    return EventReviewSession(
        event_id=session.event_id,
        company_id=session.company_id,
        findings=(history,),
    )


def test_round_trip_preserves_revisions_decisions_and_staleness() -> None:
    session = _rich_session()

    decoded = decode_session(json.loads(json.dumps(encode_session(session))))

    assert decoded == session
    history = decoded.findings[0]
    assert len(history.revisions) == 2
    assert history.decisions[0].reason == "matches model"
    assert history.decisions[0].decided_at.utcoffset() == timedelta(hours=10)
    assert history.staleness[0].superseding_version_id == "acme-q2-results:version-2"
    assert history.current_outcome is ReviewOutcome.PENDING


def test_round_trip_preserves_decimal_text_and_normalization() -> None:
    actual = ReportedObservation(
        metric="revenue",
        value=Decimal("125.10"),
        unit="AUD_millions",
        period="2026-Q2",
        basis="reported",
        evidence=EvidenceReference("doc", "doc:v1", "page=1"),
    )
    baseline = BaselineObservation(
        "revenue", Decimal("120000"), "AUD_thousands", "2026-Q2", "reported"
    )
    replay = replay_event(event_id="e", company_id="c", comparisons=((actual, baseline),))
    session = start_event_review(replay, created_at=NOW)

    decoded = decode_session(encode_session(session))

    finding = decoded.findings[0].current_revision.finding
    assert str(finding.actual) == "125.10"
    assert finding.baseline_normalization is not None
    assert finding.baseline_normalization.source_unit == "AUD_thousands"
    assert decoded == session


def test_decode_rejects_unknown_schema_version() -> None:
    payload = encode_session(_rich_session())
    payload["schema_version"] = 99

    with pytest.raises(ValueError, match="schema_version"):
        decode_session(payload)
