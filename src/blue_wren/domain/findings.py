"""Domain model for evidence-linked event findings."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from blue_wren.domain.financial_units import (
    FinancialNormalization,
    convert_financial_value,
)


class FindingStatus(StrEnum):
    """Lifecycle states implemented by the first comparison slice."""

    PROPOSED = "proposed"
    UNRESOLVED = "unresolved"


@dataclass(frozen=True, slots=True)
class EvidenceReference:
    document_id: str
    document_version_id: str
    locator: str


@dataclass(frozen=True, slots=True)
class ReportedObservation:
    metric: str
    value: Decimal
    unit: str
    period: str
    basis: str
    evidence: EvidenceReference


@dataclass(frozen=True, slots=True)
class BaselineObservation:
    metric: str
    value: Decimal
    unit: str
    period: str
    basis: str
    target: str = "estimate"


@dataclass(frozen=True, slots=True)
class Finding:
    metric: str
    actual: Decimal
    baseline: Decimal
    delta: Decimal | None
    unit: str
    period: str
    basis: str
    evidence: EvidenceReference
    status: FindingStatus
    reason: str | None = None
    baseline_normalization: FinancialNormalization | None = None
    baseline_target: str = "estimate"


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
            basis=actual.basis,
            evidence=actual.evidence,
            status=FindingStatus.UNRESOLVED,
            reason=mismatch,
            baseline_target=baseline.target,
        )

    normalized_baseline = convert_financial_value(
        baseline.value,
        source_unit=baseline.unit,
        target_unit=actual.unit,
    )
    if normalized_baseline is None:
        return Finding(
            metric=actual.metric,
            actual=actual.value,
            baseline=baseline.value,
            delta=None,
            unit=actual.unit,
            period=actual.period,
            basis=actual.basis,
            evidence=actual.evidence,
            status=FindingStatus.UNRESOLVED,
            reason="unit_mismatch",
            baseline_target=baseline.target,
        )

    return Finding(
        metric=actual.metric,
        actual=actual.value,
        baseline=normalized_baseline,
        delta=actual.value - normalized_baseline,
        unit=actual.unit,
        period=actual.period,
        basis=actual.basis,
        evidence=actual.evidence,
        status=FindingStatus.PROPOSED,
        baseline_normalization=(
            FinancialNormalization(
                source_value=baseline.value,
                source_unit=baseline.unit,
                normalized_value=normalized_baseline,
                normalized_unit=actual.unit,
            )
            if baseline.unit != actual.unit
            else None
        ),
        baseline_target=baseline.target,
    )


def _comparison_mismatch(
    actual: ReportedObservation,
    baseline: BaselineObservation,
) -> str | None:
    if actual.metric != baseline.metric:
        return "metric_mismatch"
    if actual.period != baseline.period:
        return "period_mismatch"
    if actual.basis != baseline.basis:
        return "basis_mismatch"
    return None
