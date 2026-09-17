from datetime import datetime
from decimal import Decimal
from typing import Any

from blue_wren.domain.event_review import EventReviewSession
from blue_wren.domain.financial_units import FinancialNormalization
from blue_wren.domain.findings import EvidenceReference, Finding, FindingStatus
from blue_wren.domain.review import (
    FindingHistory,
    FindingRevision,
    FindingStaleness,
    ReviewDecision,
    ReviewOutcome,
)

SCHEMA_VERSION = 1


def encode_session(session: EventReviewSession) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "event_id": session.event_id,
        "company_id": session.company_id,
        "findings": [_encode_history(history) for history in session.findings],
    }


def decode_session(payload: dict[str, Any]) -> EventReviewSession:
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"unsupported schema_version: {payload.get('schema_version')}")
    return EventReviewSession(
        event_id=payload["event_id"],
        company_id=payload["company_id"],
        findings=tuple(_decode_history(item) for item in payload["findings"]),
    )


def _encode_history(history: FindingHistory) -> dict[str, Any]:
    return {
        "revisions": [
            {
                "finding_id": revision.finding_id,
                "version": revision.version,
                "finding": _encode_finding(revision.finding),
                "created_at": revision.created_at.isoformat(),
            }
            for revision in history.revisions
        ],
        "decisions": [
            {
                "finding_id": decision.finding_id,
                "finding_version": decision.finding_version,
                "outcome": decision.outcome.value,
                "reviewer_id": decision.reviewer_id,
                "decided_at": decision.decided_at.isoformat(),
                "reason": decision.reason,
            }
            for decision in history.decisions
        ],
        "staleness": [
            {
                "finding_id": event.finding_id,
                "finding_version": event.finding_version,
                "superseded_version_id": event.superseded_version_id,
                "superseding_version_id": event.superseding_version_id,
                "marked_at": event.marked_at.isoformat(),
            }
            for event in history.staleness
        ],
    }


def _decode_history(payload: dict[str, Any]) -> FindingHistory:
    return FindingHistory(
        revisions=tuple(
            FindingRevision(
                finding_id=item["finding_id"],
                version=item["version"],
                finding=_decode_finding(item["finding"]),
                created_at=datetime.fromisoformat(item["created_at"]),
            )
            for item in payload["revisions"]
        ),
        decisions=tuple(
            ReviewDecision(
                finding_id=item["finding_id"],
                finding_version=item["finding_version"],
                outcome=ReviewOutcome(item["outcome"]),
                reviewer_id=item["reviewer_id"],
                decided_at=datetime.fromisoformat(item["decided_at"]),
                reason=item["reason"],
            )
            for item in payload["decisions"]
        ),
        staleness=tuple(
            FindingStaleness(
                finding_id=item["finding_id"],
                finding_version=item["finding_version"],
                superseded_version_id=item["superseded_version_id"],
                superseding_version_id=item["superseding_version_id"],
                marked_at=datetime.fromisoformat(item["marked_at"]),
            )
            for item in payload["staleness"]
        ),
    )


def _encode_finding(finding: Finding) -> dict[str, Any]:
    normalization = finding.baseline_normalization
    return {
        "metric": finding.metric,
        "actual": str(finding.actual),
        "baseline": str(finding.baseline),
        "delta": None if finding.delta is None else str(finding.delta),
        "unit": finding.unit,
        "period": finding.period,
        "basis": finding.basis,
        "evidence": {
            "document_id": finding.evidence.document_id,
            "document_version_id": finding.evidence.document_version_id,
            "locator": finding.evidence.locator,
        },
        "status": finding.status.value,
        "reason": finding.reason,
        "baseline_target": finding.baseline_target,
        "baseline_normalization": None
        if normalization is None
        else {
            "source_value": str(normalization.source_value),
            "source_unit": normalization.source_unit,
            "normalized_value": str(normalization.normalized_value),
            "normalized_unit": normalization.normalized_unit,
        },
    }


def _decode_finding(payload: dict[str, Any]) -> Finding:
    normalization = payload["baseline_normalization"]
    evidence = payload["evidence"]
    return Finding(
        metric=payload["metric"],
        actual=Decimal(payload["actual"]),
        baseline=Decimal(payload["baseline"]),
        delta=None if payload["delta"] is None else Decimal(payload["delta"]),
        unit=payload["unit"],
        period=payload["period"],
        basis=payload["basis"],
        evidence=EvidenceReference(
            document_id=evidence["document_id"],
            document_version_id=evidence["document_version_id"],
            locator=evidence["locator"],
        ),
        status=FindingStatus(payload["status"]),
        reason=payload["reason"],
        baseline_target=payload.get("baseline_target", "estimate"),
        baseline_normalization=None
        if normalization is None
        else FinancialNormalization(
            source_value=Decimal(normalization["source_value"]),
            source_unit=normalization["source_unit"],
            normalized_value=Decimal(normalization["normalized_value"]),
            normalized_unit=normalization["normalized_unit"],
        ),
    )
