from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from blue_wren.domain.findings import BaselineObservation, ReportedObservation


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


class RunStatus(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    FAILED = "failed"


class RunFailureCode(StrEnum):
    SCOPE_TOO_LARGE = "scope_too_large"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    PROVIDER_REFUSED = "provider_refused"
    PROVIDER_REJECTED = "provider_rejected"
    OUTPUT_TRUNCATED = "output_truncated"
    DEADLINE_EXCEEDED = "deadline_exceeded"
    TOOL_BUDGET_EXCEEDED = "tool_budget_exceeded"
    CANCELLED = "cancelled"


class ToolCallStatus(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"
    DENIED = "denied"


@dataclass(frozen=True, slots=True)
class BudgetUsage:
    prompt_chars: int
    input_tokens: int
    output_tokens: int
    cache_read_input_tokens: int
    provider_calls: int
    tool_calls: int
    elapsed_seconds: Decimal


@dataclass(frozen=True, slots=True)
class ProviderAttempt:
    index: int
    outcome: str
    request_id: str | None
    model_id: str | None
    input_tokens: int
    output_tokens: int
    duration_seconds: Decimal


@dataclass(frozen=True, slots=True)
class ToolCallRecord:
    index: int
    name: str
    status: ToolCallStatus
    argument_digest: str
    duration_seconds: Decimal


@dataclass(frozen=True, slots=True)
class AnalysisRun:
    run_id: str
    event_id: str
    company_id: str
    idempotency_key: str
    request_digest: str
    scope_digest: str
    baseline_digest: str
    status: RunStatus
    failure: RunFailureCode | None
    cutoff_at: datetime
    source_version_ids: tuple[str, ...]
    requested_metrics: tuple[str, ...]
    provider_id: str
    model_id: str
    prompt_version: str
    output_schema_version: str
    validator_version: str
    budget: RunBudget
    usage: BudgetUsage
    attempts: tuple[ProviderAttempt, ...]
    tool_calls: tuple[ToolCallRecord, ...]
    proposed: tuple[ReportedObservation, ...]
    rejected: tuple[RejectedProposal, ...]
    started_at: datetime
    finished_at: datetime
