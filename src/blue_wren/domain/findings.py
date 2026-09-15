"""Domain model for evidence-linked event findings."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum


class FindingStatus(StrEnum):
    """Lifecycle states implemented by the first comparison slice."""

    PROPOSED = "proposed"
    UNRESOLVED = "unresolved"


@dataclass(frozen=True, slots=True)
class EvidenceReference:
    document_id: str
    locator: str


@dataclass(frozen=True, slots=True)
class ReportedObservation:
    metric: str
    value: Decimal
    unit: str
    period: str
    evidence: EvidenceReference


@dataclass(frozen=True, slots=True)
class BaselineObservation:
    metric: str
    value: Decimal
    unit: str
    period: str


@dataclass(frozen=True, slots=True)
class Finding:
    metric: str
    actual: Decimal
    baseline: Decimal
    delta: Decimal | None
    unit: str
    period: str
    evidence: EvidenceReference
    status: FindingStatus
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class EventReplayResult:
    event_id: str
    company_id: str
    findings: tuple[Finding, ...]


def compare_observations(
    actual: ReportedObservation,
    baseline: BaselineObservation,
) -> Finding:
    """Compare like-for-like observations or explain why they are unresolved."""
    mismatch = _comparison_mismatch(actual, baseline)
    if mismatch is not None:
        return Finding(
            metric=actual.metric,
            actual=actual.value,
            baseline=baseline.value,
            delta=None,
            unit=actual.unit,
            period=actual.period,
            evidence=actual.evidence,
            status=FindingStatus.UNRESOLVED,
            reason=mismatch,
        )

    return Finding(
        metric=actual.metric,
        actual=actual.value,
        baseline=baseline.value,
        delta=actual.value - baseline.value,
        unit=actual.unit,
        period=actual.period,
        evidence=actual.evidence,
        status=FindingStatus.PROPOSED,
    )


def _comparison_mismatch(
    actual: ReportedObservation,
    baseline: BaselineObservation,
) -> str | None:
    if actual.metric != baseline.metric:
        return "metric_mismatch"
    if actual.unit != baseline.unit:
        return "unit_mismatch"
    if actual.period != baseline.period:
        return "period_mismatch"
    return None
