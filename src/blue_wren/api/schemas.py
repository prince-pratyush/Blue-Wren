from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from blue_wren.domain.analysis import ProposalRejectionCode, RunFailureCode, RunStatus
from blue_wren.domain.evidence import RightsBasis
from blue_wren.domain.exporting import ExportBlockerCode
from blue_wren.domain.extraction import ExtractionStatus
from blue_wren.domain.review import ReviewOutcome

Identifier = Annotated[str, Field(min_length=1, max_length=128)]
EvidenceVersionIdentifier = Annotated[str, Field(min_length=1, max_length=256)]
Locator = Annotated[str, Field(min_length=1, max_length=512)]
FinancialValue = Annotated[Decimal, Field(allow_inf_nan=False, max_digits=30)]


class EvidenceReferenceRequest(BaseModel):
    document_id: Identifier
    document_version_id: EvidenceVersionIdentifier
    locator: Locator


class ReportedObservationRequest(BaseModel):
    metric: Identifier
    value: FinancialValue
    unit: Identifier
    period: Identifier
    basis: Identifier
    evidence: EvidenceReferenceRequest


class BaselineObservationRequest(BaseModel):
    metric: Identifier
    value: FinancialValue
    unit: Identifier
    period: Identifier
    basis: Identifier
    target: Literal["estimate", "consensus", "guidance", "prior_period"] = "estimate"


class ObservationComparisonRequest(BaseModel):
    actual: ReportedObservationRequest
    baseline: BaselineObservationRequest


class EventReplayRequest(BaseModel):
    event_id: Identifier
    company_id: Identifier
    comparisons: Annotated[list[ObservationComparisonRequest], Field(min_length=1, max_length=500)]


class EvidenceReferenceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    document_id: str
    document_version_id: str
    locator: str


class FinancialNormalizationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    source_value: Decimal
    source_unit: str
    normalized_value: Decimal
    normalized_unit: str


class FindingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    metric: str
    actual: Decimal
    baseline: Decimal
    delta: Decimal | None
    unit: str
    period: str
    basis: str
    evidence: EvidenceReferenceResponse
    status: Literal["proposed", "unresolved"]
    reason: str | None
    baseline_normalization: FinancialNormalizationResponse | None
    baseline_target: str


class EventReplayResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    event_id: str
    company_id: str
    findings: list[FindingResponse]


class ReviewDecisionRequest(BaseModel):
    expected_revision: Annotated[int, Field(ge=1)] | None = None
    expected_version: Annotated[int, Field(ge=1)]
    outcome: Literal["accepted", "rejected", "deferred"]
    reviewer_id: Identifier
    reason: Annotated[str, Field(max_length=2000)] | None = None


class ReviewedFindingResponse(BaseModel):
    finding_id: str
    version: int
    outcome: ReviewOutcome
    citation_resolved: bool
    finding: FindingResponse


class EventReviewResponse(BaseModel):
    event_id: str
    company_id: str
    revision: int
    findings: list[ReviewedFindingResponse]


class EventReviewSummaryResponse(BaseModel):
    event_id: str
    company_id: str
    revision: int
    findings_total: int
    findings_pending: int
    citations_unresolved: int


class ExportBlockerResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    finding_id: str
    code: ExportBlockerCode


class ExportReadinessResponse(BaseModel):
    event_id: str
    revision: int
    allowed: bool
    blockers: list[ExportBlockerResponse]


class TextSpanResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    page: int
    index: int
    text: str
    locator: str


class ExtractionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    document_version_id: str
    status: ExtractionStatus
    page_count: int | None
    reason: str | None
    spans: list[TextSpanResponse]


class CompanyRequest(BaseModel):
    company_id: Identifier
    name: Annotated[str, Field(min_length=1, max_length=256)]
    exchange: Annotated[str, Field(min_length=1, max_length=32)]


class CompanyResponse(BaseModel):
    company_id: str
    name: str
    exchange: str
    events_total: int
    findings_pending: int


class RunBudgetRequest(BaseModel):
    max_prompt_chars: Annotated[int, Field(ge=1000, le=400_000)] = 60_000
    max_output_tokens: Annotated[int, Field(ge=256, le=32_000)] = 4_000
    max_provider_calls: Annotated[int, Field(ge=1, le=5)] = 2
    max_tool_calls: Literal[0] = 0
    max_seconds: Annotated[Decimal, Field(gt=0, le=600)] = Decimal("120")


class AnalysisRunRequest(BaseModel):
    event_id: Identifier
    company_id: Identifier
    idempotency_key: Annotated[str, Field(min_length=1, max_length=128)]
    cutoff_at: datetime
    source_version_ids: Annotated[
        list[EvidenceVersionIdentifier], Field(min_length=1, max_length=50)
    ]
    baselines: Annotated[list[BaselineObservationRequest], Field(min_length=1, max_length=200)]
    units: list[Identifier] = []
    budget: RunBudgetRequest = RunBudgetRequest()


class AnalysisReviewRequest(BaseModel):
    baselines: Annotated[list[BaselineObservationRequest], Field(min_length=1, max_length=200)]


class RunBudgetResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    max_prompt_chars: int
    max_output_tokens: int
    max_provider_calls: int
    max_tool_calls: int
    max_seconds: Decimal


class BudgetUsageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    prompt_chars: int
    input_tokens: int
    output_tokens: int
    cache_read_input_tokens: int
    provider_calls: int
    tool_calls: int
    elapsed_seconds: Decimal


class ProviderAttemptResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    index: int
    outcome: str
    request_id: str | None
    model_id: str | None
    input_tokens: int
    output_tokens: int
    duration_seconds: Decimal


class ProposedObservationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    metric: str
    value: Decimal
    unit: str
    period: str
    basis: str
    evidence: EvidenceReferenceResponse


class RejectedProposalResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: ProposalRejectionCode
    metric: str | None
    document_version_id: str | None
    locator: str | None
    detail: str | None


class AnalysisRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    run_id: str
    event_id: str
    company_id: str
    idempotency_key: str
    request_digest: str
    scope_digest: str
    status: RunStatus
    failure: RunFailureCode | None
    cutoff_at: datetime
    source_version_ids: list[str]
    requested_metrics: list[str]
    provider_id: str
    model_id: str
    prompt_version: str
    output_schema_version: str
    validator_version: str
    budget: RunBudgetResponse
    usage: BudgetUsageResponse
    attempts: list[ProviderAttemptResponse]
    proposed: list[ProposedObservationResponse]
    rejected: list[RejectedProposalResponse]
    started_at: datetime
    finished_at: datetime


class AnalysisRunSummaryResponse(BaseModel):
    run_id: str
    event_id: str
    status: RunStatus
    failure: RunFailureCode | None
    proposed_count: int
    rejected_count: int
    provider_calls: int
    model_id: str
    started_at: datetime


class ExportedSourceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    document_id: str
    document_version_id: str
    content_sha256: str
    source_name: str
    published_at: datetime
    available_at: datetime


class ExportedFindingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    finding_id: str
    version: int
    metric: str
    actual: Decimal
    baseline: Decimal
    delta: Decimal
    unit: str
    period: str
    basis: str
    baseline_target: str
    reviewer_id: str
    decided_at: datetime
    document_id: str
    document_version_id: str
    locator: str
    evidence_text: str


class ExportManifestResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    event_id: str
    company_id: str
    revision: int
    generated_at: datetime
    findings: list[ExportedFindingResponse]
    sources: list[ExportedSourceResponse]


class DocumentVersionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    document_id: str
    version_id: str
    content_sha256: str
    byte_size: int
    media_type: str
    source_name: str
    rights_basis: RightsBasis
    published_at: datetime
    available_at: datetime
    ingested_at: datetime
