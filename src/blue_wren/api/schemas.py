from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

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
    expected_revision: Annotated[int, Field(ge=1)]
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
