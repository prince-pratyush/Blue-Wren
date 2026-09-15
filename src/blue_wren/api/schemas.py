from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

Identifier = Annotated[str, Field(min_length=1, max_length=128)]
Locator = Annotated[str, Field(min_length=1, max_length=512)]
FinancialValue = Annotated[Decimal, Field(allow_inf_nan=False, max_digits=30)]


class EvidenceReferenceRequest(BaseModel):
    document_id: Identifier
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
    locator: str


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


class EventReplayResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    event_id: str
    company_id: str
    findings: list[FindingResponse]
