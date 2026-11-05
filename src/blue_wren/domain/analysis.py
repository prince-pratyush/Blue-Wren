from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from blue_wren.domain.findings import BaselineObservation


@dataclass(frozen=True, slots=True)
class SourceSpan:
    document_id: str
    document_version_id: str
    page: int
    index: int
    locator: str
    text: str


@dataclass(frozen=True, slots=True)
class AnalysisScope:
    event_id: str
    company_id: str
    cutoff_at: datetime
    metrics: tuple[str, ...]
    units: tuple[str, ...]
    spans: tuple[SourceSpan, ...]
    baselines: tuple[BaselineObservation, ...]


@dataclass(frozen=True, slots=True)
class RunBudget:
    max_prompt_chars: int
    max_output_tokens: int
    max_provider_calls: int
    max_tool_calls: int
    max_seconds: Decimal


class ProposalRejectionCode(StrEnum):
    MALFORMED_OUTPUT = "malformed_output"
    METRIC_UNKNOWN = "metric_unknown"
    SPAN_NOT_IN_SCOPE = "span_not_in_scope"
    VALUE_NOT_VERBATIM = "value_not_verbatim"
    VALUE_NOT_NUMERIC = "value_not_numeric"
    PERIOD_MISSING = "period_missing"
    UNIT_MISSING = "unit_missing"
    BASIS_MISSING = "basis_missing"
    DUPLICATE_PROPOSAL = "duplicate_proposal"


@dataclass(frozen=True, slots=True)
class RejectedProposal:
    code: ProposalRejectionCode
    metric: str | None
    document_version_id: str | None
    locator: str | None
    detail: str | None
