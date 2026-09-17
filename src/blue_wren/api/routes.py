from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status

from blue_wren.api.schemas import (
    CompanyRequest,
    CompanyResponse,
    DocumentVersionResponse,
    EventReplayRequest,
    EventReplayResponse,
    EventReviewResponse,
    EventReviewSummaryResponse,
    ExportBlockerResponse,
    ExportReadinessResponse,
    ExtractionResponse,
    FindingResponse,
    ObservationComparisonRequest,
    ReviewDecisionRequest,
    ReviewedFindingResponse,
)
from blue_wren.application.company_store import CompanyConflict, CompanyRepository
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
from blue_wren.application.extraction import extract_text
from blue_wren.application.extraction_store import ExtractionNotFound, ExtractionRepository
from blue_wren.application.replay import replay_event
from blue_wren.application.review_store import (
    EventReviewNotFound,
    EventReviewRepository,
    EventReviewStoreConflict,
    StoredEventReview,
)
from blue_wren.domain.company import Company
from blue_wren.domain.evidence import DocumentVersion, EvidenceIntakeError, RightsBasis
from blue_wren.domain.extraction import (
    ExtractionError,
    ExtractionRecord,
    ExtractionStatus,
    ExtractionUnsupported,
)
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


def _companies(request: Request) -> CompanyRepository:
    repository: CompanyRepository = request.app.state.companies
    return repository


def _extractions(request: Request) -> ExtractionRepository:
    repository: ExtractionRepository = request.app.state.extractions
    return repository


@router.post("/companies", response_model=CompanyResponse, status_code=status.HTTP_201_CREATED)
def create_company(
    request: CompanyRequest,
    companies: Annotated[CompanyRepository, Depends(_companies)],
    reviews: Annotated[EventReviewRepository, Depends(_event_reviews)],
) -> CompanyResponse:
    try:
        company = companies.create(
            Company(company_id=request.company_id, name=request.name, exchange=request.exchange)
        )
    except CompanyConflict as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    return _company_response(company, reviews.list())


@router.get("/companies", response_model=list[CompanyResponse])
def list_companies(
    companies: Annotated[CompanyRepository, Depends(_companies)],
    reviews: Annotated[EventReviewRepository, Depends(_event_reviews)],
) -> list[CompanyResponse]:
    stored = reviews.list()
    return [_company_response(company, stored) for company in companies.list()]


def _company_response(
    company: Company, reviews: tuple[StoredEventReview, ...]
) -> CompanyResponse:
    own = [stored for stored in reviews if stored.session.company_id == company.company_id]
    return CompanyResponse(
        company_id=company.company_id,
        name=company.name,
        exchange=company.exchange,
        events_total=len(own),
        findings_pending=sum(
            history.current_outcome is ReviewOutcome.PENDING
            for stored in own
            for history in stored.session.findings
        ),
    )


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
    extractions: Annotated[ExtractionRepository, Depends(_extractions)],
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
    extractions.put(_extraction_record(stored, content))
    return DocumentVersionResponse.model_validate(stored)


@router.get("/evidence/versions/{version_id}/spans", response_model=ExtractionResponse)
def get_evidence_spans(
    version_id: str,
    extractions: Annotated[ExtractionRepository, Depends(_extractions)],
) -> ExtractionResponse:
    try:
        record = extractions.get(version_id)
    except ExtractionNotFound as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    return ExtractionResponse.model_validate(record)


def _extraction_record(version: DocumentVersion, content: bytes) -> ExtractionRecord:
    try:
        extracted = extract_text(version, content)
    except ExtractionUnsupported as error:
        return ExtractionRecord(
            document_version_id=version.version_id,
            status=ExtractionStatus.UNSUPPORTED,
            page_count=None,
            spans=(),
            reason=str(error),
        )
    except ExtractionError as error:
        return ExtractionRecord(
            document_version_id=version.version_id,
            status=ExtractionStatus.FAILED,
            page_count=None,
            spans=(),
            reason=str(error),
        )
    return ExtractionRecord(
        document_version_id=version.version_id,
        status=ExtractionStatus.EXTRACTED,
        page_count=extracted.page_count,
        spans=extracted.spans,
    )


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
    evidence: Annotated[EvidenceVersionRepository, Depends(_evidence_versions)],
    extractions: Annotated[ExtractionRepository, Depends(_extractions)],
) -> EventReviewResponse:
    replay = _replay(request)
    try:
        for finding in replay.findings:
            _require_ingested(evidence, finding.evidence)
    except (EvidenceVersionNotFound, EvidenceIntakeError) as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)
        ) from error
    try:
        session = start_event_review(replay, created_at=datetime.now(UTC))
    except EventReviewError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)
        ) from error
    try:
        stored = repository.create(session)
    except EventReviewStoreConflict as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    return _review_response(stored, extractions)


@router.get("/event-reviews", response_model=list[EventReviewSummaryResponse])
def list_event_reviews(
    repository: Annotated[EventReviewRepository, Depends(_event_reviews)],
    extractions: Annotated[ExtractionRepository, Depends(_extractions)],
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
            citations_unresolved=sum(
                not _citation_resolved(extractions, history.current_revision.finding.evidence)
                for history in stored.session.findings
            ),
        )
        for stored in repository.list()
    ]


@router.get("/event-reviews/{event_id}", response_model=EventReviewResponse)
def get_event_review(
    event_id: str,
    repository: Annotated[EventReviewRepository, Depends(_event_reviews)],
    extractions: Annotated[ExtractionRepository, Depends(_extractions)],
) -> EventReviewResponse:
    try:
        stored = repository.get(event_id)
    except EventReviewNotFound as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    return _review_response(stored, extractions)


@router.get(
    "/event-reviews/{event_id}/export-readiness",
    response_model=ExportReadinessResponse,
)
def get_export_readiness(
    event_id: str,
    repository: Annotated[EventReviewRepository, Depends(_event_reviews)],
    extractions: Annotated[ExtractionRepository, Depends(_extractions)],
) -> ExportReadinessResponse:
    try:
        stored = repository.get(event_id)
    except EventReviewNotFound as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    readiness = assess_checked_export(
        stored.session.findings,
        citation_resolved=lambda evidence: _citation_resolved(extractions, evidence),
    )
    return ExportReadinessResponse(
        event_id=event_id,
        revision=stored.revision,
        allowed=readiness.allowed,
        blockers=[ExportBlockerResponse.model_validate(blocker) for blocker in readiness.blockers],
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
    extractions: Annotated[ExtractionRepository, Depends(_extractions)],
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
    return _review_response(updated, extractions)


def _require_ingested(repository: EvidenceVersionRepository, reference: EvidenceReference) -> None:
    version = repository.get(reference.document_version_id)
    if version.document_id != reference.document_id:
        raise EvidenceIntakeError(
            f"evidence version {reference.document_version_id} belongs to "
            f"{version.document_id}, not {reference.document_id}"
        )


def _citation_resolved(extractions: ExtractionRepository, evidence: EvidenceReference) -> bool:
    try:
        record = extractions.get(evidence.document_version_id)
    except ExtractionNotFound:
        return False
    return record.status is ExtractionStatus.EXTRACTED and any(
        span.locator == evidence.locator for span in record.spans
    )


def _review_response(
    stored: StoredEventReview, extractions: ExtractionRepository
) -> EventReviewResponse:
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
                citation_resolved=_citation_resolved(
                    extractions, history.current_revision.finding.evidence
                ),
                finding=FindingResponse.model_validate(history.current_revision.finding),
            )
            for history in session.findings
        ],
    )


def _replay(request: EventReplayRequest) -> EventReplayResult:
    return replay_event(
        event_id=request.event_id,
        company_id=request.company_id,
        comparisons=tuple(_comparison(item) for item in request.comparisons),
    )


def _comparison(
    item: ObservationComparisonRequest,
) -> tuple[ReportedObservation, BaselineObservation]:
    actual = ReportedObservation(
        metric=item.actual.metric,
        value=item.actual.value,
        unit=item.actual.unit,
        period=item.actual.period,
        basis=item.actual.basis,
        evidence=EvidenceReference(
            document_id=item.actual.evidence.document_id,
            document_version_id=item.actual.evidence.document_version_id,
            locator=item.actual.evidence.locator,
        ),
    )
    baseline = BaselineObservation(
        metric=item.baseline.metric,
        value=item.baseline.value,
        unit=item.baseline.unit,
        period=item.baseline.period,
        basis=item.baseline.basis,
    )
    return actual, baseline
