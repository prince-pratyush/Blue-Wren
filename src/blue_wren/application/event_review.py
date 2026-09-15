from dataclasses import replace
from datetime import datetime
from hashlib import sha256

from blue_wren.application.review import create_finding_history, record_review_decision
from blue_wren.domain.event_review import EventReviewSession
from blue_wren.domain.findings import EventReplayResult, Finding
from blue_wren.domain.review import ReviewOutcome


class EventReviewError(ValueError):
    pass


def start_event_review(
    replay: EventReplayResult,
    *,
    created_at: datetime,
) -> EventReviewSession:
    histories = tuple(
        create_finding_history(
            _finding_id(replay.event_id, replay.company_id, finding),
            finding,
            created_at,
        )
        for finding in replay.findings
    )
    identities = tuple(history.current_revision.finding_id for history in histories)
    if len(set(identities)) != len(identities):
        raise EventReviewError("duplicate finding identity")
    return EventReviewSession(
        event_id=replay.event_id,
        company_id=replay.company_id,
        findings=histories,
    )


def decide_event_finding(
    session: EventReviewSession,
    *,
    finding_id: str,
    expected_version: int,
    outcome: ReviewOutcome,
    reviewer_id: str,
    decided_at: datetime,
    reason: str | None = None,
) -> EventReviewSession:
    if not any(
        history.current_revision.finding_id == finding_id for history in session.findings
    ):
        raise EventReviewError(f"finding not found: {finding_id}")
    findings = tuple(
        record_review_decision(
            history,
            expected_version=expected_version,
            outcome=outcome,
            reviewer_id=reviewer_id,
            decided_at=decided_at,
            reason=reason,
        )
        if history.current_revision.finding_id == finding_id
        else history
        for history in session.findings
    )
    return replace(session, findings=findings)


def _finding_id(event_id: str, company_id: str, finding: Finding) -> str:
    evidence = finding.evidence
    identity = "\x1f".join(
        (
            event_id,
            company_id,
            finding.metric,
            finding.unit,
            finding.period,
            evidence.document_id,
            evidence.document_version_id,
            evidence.locator,
        )
    )
    return f"finding-{sha256(identity.encode()).hexdigest()[:24]}"
