from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from blue_wren.domain.evidence import RightsBasis

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
    evidence: EvidenceReferenceRequest


class BaselineObservationRequest(BaseModel):
    metric: Identifier
    value: FinancialValue
    unit: Identifier
    period: Identifier


class EventReplayRequest(BaseModel):
    event_id: Identifier
    company_id: Identifier
    actual: ReportedObservationRequest
    baseline: BaselineObservationRequest


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
    evidence: EvidenceReferenceResponse
    status: Literal["proposed", "unresolved"]
    reason: str | None
    baseline_normalization: FinancialNormalizationResponse | None


class EventReplayResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    event_id: str
    company_id: str
    findings: list[FindingResponse]


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
