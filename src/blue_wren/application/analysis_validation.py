import re
from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation

from blue_wren.application.analysis_schema import BASES, PERIOD_PATTERN
from blue_wren.domain.analysis import (
    AnalysisScope,
    ProposalRejectionCode,
    RejectedProposal,
    SourceSpan,
)
from blue_wren.domain.findings import EvidenceReference, ReportedObservation

VALIDATOR_VERSION = "analysis-validators.v1"
_PERIOD = re.compile(PERIOD_PATTERN)
_NUMBER = re.compile(r"^\(?[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?\)?$")


def validate_proposals(
    scope: AnalysisScope,
    proposals: Sequence[Mapping[str, str]],
) -> tuple[tuple[ReportedObservation, ...], tuple[RejectedProposal, ...]]:
    spans = {(span.document_version_id, span.locator): span for span in scope.spans}
    accepted: list[ReportedObservation] = []
    rejected: list[RejectedProposal] = []
    seen: set[tuple[str, str, str, str]] = set()
    for proposal in proposals:
        outcome = _check(scope, spans, proposal, seen)
        if isinstance(outcome, ReportedObservation):
            accepted.append(outcome)
        else:
            rejected.append(outcome)
    return tuple(accepted), tuple(rejected)


def parse_verbatim_value(value_text: str, span_text: str) -> Decimal | None:
    pattern = r"(?<![0-9.,])" + re.escape(value_text) + r"(?![0-9,]|\.[0-9])"
    if re.search(pattern, span_text) is None:
        return None
    return _parse_number(value_text)


def _parse_number(value_text: str) -> Decimal | None:
    if _NUMBER.match(value_text) is None:
        return None
    negative = value_text.startswith("(") and value_text.endswith(")")
    if value_text.startswith("(") != value_text.endswith(")"):
        return None
    digits = value_text.strip("()").replace(",", "")
    try:
        value = Decimal(digits)
    except InvalidOperation:
        return None
    return -value if negative else value


def _check(
    scope: AnalysisScope,
    spans: Mapping[tuple[str, str], SourceSpan],
    proposal: Mapping[str, str],
    seen: set[tuple[str, str, str, str]],
) -> ReportedObservation | RejectedProposal:
    metric = proposal["metric"]
    version_id = proposal["document_version_id"]
    locator = proposal["locator"]

    def reject(code: ProposalRejectionCode, detail: str) -> RejectedProposal:
        return RejectedProposal(code, metric, version_id, locator, detail)

    if metric not in scope.metrics:
        return reject(ProposalRejectionCode.METRIC_UNKNOWN, metric)
    span = spans.get((version_id, locator))
    if span is None:
        return reject(ProposalRejectionCode.SPAN_NOT_IN_SCOPE, f"{version_id} {locator}")
    value_text = proposal["value_text"]
    pattern = r"(?<![0-9.,])" + re.escape(value_text) + r"(?![0-9,]|\.[0-9])"
    if not value_text or re.search(pattern, span.text) is None:
        return reject(ProposalRejectionCode.VALUE_NOT_VERBATIM, value_text)
    value = _parse_number(value_text)
    if value is None:
        return reject(ProposalRejectionCode.VALUE_NOT_NUMERIC, value_text)
    period = proposal["period"]
    if _PERIOD.match(period) is None:
        return reject(ProposalRejectionCode.PERIOD_MISSING, period)
    unit = proposal["unit"]
    if unit not in scope.units:
        return reject(ProposalRejectionCode.UNIT_MISSING, unit)
    basis = proposal["basis"]
    if basis not in BASES:
        return reject(ProposalRejectionCode.BASIS_MISSING, basis)
    key = (metric, period, basis, locator)
    if key in seen:
        return reject(ProposalRejectionCode.DUPLICATE_PROPOSAL, locator)
    seen.add(key)
    return ReportedObservation(
        metric=metric,
        value=value,
        unit=unit,
        period=period,
        basis=basis,
        evidence=EvidenceReference(
            document_id=span.document_id,
            document_version_id=span.document_version_id,
            locator=span.locator,
        ),
    )
