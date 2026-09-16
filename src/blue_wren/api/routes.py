from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status

from blue_wren.api.schemas import (
    DocumentVersionResponse,
    EventReplayRequest,
    EventReplayResponse,
    EventReviewResponse,
    EventReviewSummaryResponse,
    ExportBlockerResponse,
    ExportReadinessResponse,
    FindingResponse,
    ReviewDecisionRequest,
    ReviewedFindingResponse,
)
from blue_wren.application.event_review import (
    EventReviewError,
    decide_event_finding,
    start_event_review,
)
from blue_wren.application.evidence import DEFAULT_MAX_BYTES, ingest_evidence
from blue_wren.application.evidence_store import (
    EvidenceVersionConflict,
    EvidenceVersionNotFound,
    EvidenceVersionRepository,
)
from blue_wren.application.exporting import assess_checked_export
from blue_wren.application.replay import replay_event
from blue_wren.application.review_store import (
    EventReviewNotFound,
    EventReviewRepository,
    EventReviewStoreConflict,
    StoredEventReview,
)
from blue_wren.domain.evidence import EvidenceIntakeError, RightsBasis
from blue_wren.domain.findings import (
    BaselineObservation,
    EventReplayResult,
    EvidenceReference,
    ReportedObservation,
)
from blue_wren.domain.review import ReviewConflict, ReviewOutcome, ReviewValidationError

router = APIRouter()


def _event_reviews(request: Request) -> EventReviewRepository:
    repository: EventReviewRepository = request.app.state.event_reviews
    return repository


def _evidence_versions(request: Request) -> EvidenceVersionRepository:
    repository: EvidenceVersionRepository = request.app.state.evidence_versions
    return repository


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
    repository: Annotated[EvidenceVersionRepository, Depends(_evidence_versions)],
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
        stored = repository.put(version)
    except EvidenceIntakeError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error
    except EvidenceVersionConflict as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    return DocumentVersionResponse.model_validate(stored)


@router.get("/evidence/versions/{version_id}", response_model=DocumentVersionResponse)
def get_evidence_version(
    version_id: str,
    repository: Annotated[EvidenceVersionRepository, Depends(_evidence_versions)],
) -> DocumentVersionResponse:
    try:
        version = repository.get(version_id)
    except EvidenceVersionNotFound as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    return DocumentVersionResponse.model_validate(version)


@router.post("/event-replays", response_model=EventReplayResponse)
def create_event_replay(request: EventReplayRequest) -> EventReplayResponse:
    return EventReplayResponse.model_validate(_replay(request))


@router.post(
    "/event-reviews",
    response_model=EventReviewResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_event_review(
    request: EventReplayRequest,
    repository: Annotated[EventReviewRepository, Depends(_event_reviews)],
) -> EventReviewResponse:
    session = start_event_review(_replay(request), created_at=datetime.now(UTC))
    try:
        stored = repository.create(session)
    except EventReviewStoreConflict as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    return _review_response(stored)


@router.get("/event-reviews", response_model=list[EventReviewSummaryResponse])
def list_event_reviews(
    repository: Annotated[EventReviewRepository, Depends(_event_reviews)],
) -> list[EventReviewSummaryResponse]:
    return [
        EventReviewSummaryResponse(
            event_id=stored.session.event_id,
            company_id=stored.session.company_id,
            revision=stored.revision,
            findings_total=len(stored.session.findings),
            findings_pending=sum(
                history.current_outcome is ReviewOutcome.PENDING
                for history in stored.session.findings
            ),
        )
        for stored in repository.list()
    ]


@router.get("/event-reviews/{event_id}", response_model=EventReviewResponse)
def get_event_review(
    event_id: str,
    repository: Annotated[EventReviewRepository, Depends(_event_reviews)],
) -> EventReviewResponse:
    try:
        stored = repository.get(event_id)
    except EventReviewNotFound as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    return _review_response(stored)


@router.get(
    "/event-reviews/{event_id}/export-readiness",
    response_model=ExportReadinessResponse,
)
def get_export_readiness(
    event_id: str,
    repository: Annotated[EventReviewRepository, Depends(_event_reviews)],
) -> ExportReadinessResponse:
    try:
        stored = repository.get(event_id)
    except EventReviewNotFound as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    readiness = assess_checked_export(stored.session.findings)
    return ExportReadinessResponse(
        event_id=event_id,
        revision=stored.revision,
        allowed=readiness.allowed,
        blockers=[
            ExportBlockerResponse.model_validate(blocker) for blocker in readiness.blockers
        ],
    )


@router.post(
    "/event-reviews/{event_id}/findings/{finding_id}/decisions",
    response_model=EventReviewResponse,
)
def create_review_decision(
    event_id: str,
    finding_id: str,
    request: ReviewDecisionRequest,
    repository: Annotated[EventReviewRepository, Depends(_event_reviews)],
) -> EventReviewResponse:
    try:
        stored = repository.get(event_id)
        if stored.revision != request.expected_revision:
            raise EventReviewStoreConflict(
                f"expected revision {request.expected_revision}, "
                f"current revision is {stored.revision}"
            )
        session = decide_event_finding(
            stored.session,
            finding_id=finding_id,
            expected_version=request.expected_version,
            outcome=ReviewOutcome(request.outcome),
            reviewer_id=request.reviewer_id,
            decided_at=datetime.now(UTC),
            reason=request.reason,
        )
        updated = repository.update(session, expected_revision=request.expected_revision)
    except (EventReviewNotFound, EventReviewError) as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except (EventReviewStoreConflict, ReviewConflict) as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    except ReviewValidationError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)
        ) from error
    return _review_response(updated)


def _review_response(stored: StoredEventReview) -> EventReviewResponse:
    session = stored.session
    return EventReviewResponse(
        event_id=session.event_id,
        company_id=session.company_id,
        revision=stored.revision,
        findings=[
            ReviewedFindingResponse(
                finding_id=history.current_revision.finding_id,
                version=history.current_revision.version,
                outcome=history.current_outcome,
                finding=FindingResponse.model_validate(history.current_revision.finding),
            )
            for history in session.findings
        ],
    )


def _replay(request: EventReplayRequest) -> EventReplayResult:
    actual = ReportedObservation(
        metric=request.actual.metric,
        value=request.actual.value,
        unit=request.actual.unit,
        period=request.actual.period,
        basis=request.actual.basis,
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
        basis=request.baseline.basis,
    )
    return replay_event(
        event_id=request.event_id,
        company_id=request.company_id,
        actual=actual,
        baseline=baseline,
    )
