from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status

from blue_wren.api.schemas import (
    DocumentVersionResponse,
    EventReplayRequest,
    EventReplayResponse,
)
from blue_wren.application.evidence import DEFAULT_MAX_BYTES, ingest_evidence
from blue_wren.application.replay import replay_event
from blue_wren.domain.evidence import EvidenceIntakeError, RightsBasis
from blue_wren.domain.findings import (
    BaselineObservation,
    EvidenceReference,
    ReportedObservation,
)

router = APIRouter()


@router.post(
    "/evidence/versions",
    response_model=DocumentVersionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_evidence_version(
    document_id: Annotated[str, Form(min_length=1, max_length=128)],
    source_name: Annotated[str, Form(min_length=1, max_length=256)],
    rights_basis: Annotated[RightsBasis, Form()],
    published_at: Annotated[datetime, Form()],
    available_at: Annotated[datetime, Form()],
    file: Annotated[UploadFile, File()],
) -> DocumentVersionResponse:
    content = await file.read(DEFAULT_MAX_BYTES + 1)
    try:
        version = ingest_evidence(
            document_id=document_id,
            content=content,
            media_type=file.content_type or "application/octet-stream",
            source_name=source_name,
            rights_basis=rights_basis,
            published_at=published_at,
            available_at=available_at,
            ingested_at=datetime.now(UTC),
        )
    except EvidenceIntakeError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error
    return DocumentVersionResponse.model_validate(version)


@router.post("/event-replays", response_model=EventReplayResponse)
def create_event_replay(request: EventReplayRequest) -> EventReplayResponse:
    actual = ReportedObservation(
        metric=request.actual.metric,
        value=request.actual.value,
        unit=request.actual.unit,
        period=request.actual.period,
        evidence=EvidenceReference(
            document_id=request.actual.evidence.document_id,
            document_version_id=request.actual.evidence.document_version_id,
            locator=request.actual.evidence.locator,
        ),
    )
    baseline = BaselineObservation(
        metric=request.baseline.metric,
        value=request.baseline.value,
        unit=request.baseline.unit,
        period=request.baseline.period,
    )
    result = replay_event(
        event_id=request.event_id,
        company_id=request.company_id,
        actual=actual,
        baseline=baseline,
    )
    return EventReplayResponse.model_validate(result)
