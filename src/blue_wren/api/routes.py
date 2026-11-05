import secrets
import time
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    Response,
    UploadFile,
    status,
)

from blue_wren.api.schemas import (
    AnalysisReviewRequest,
    AnalysisRunRequest,
    AnalysisRunResponse,
    AnalysisRunSummaryResponse,
    BaselineObservationRequest,
    CompanyRequest,
    CompanyResponse,
    DocumentVersionResponse,
    EventReplayRequest,
    EventReplayResponse,
    EventReviewResponse,
    EventReviewSummaryResponse,
    ExportBlockerResponse,
    ExportManifestResponse,
    ExportReadinessResponse,
    ExtractionResponse,
    FindingResponse,
    ObservationComparisonRequest,
    ReviewDecisionRequest,
    ReviewedFindingResponse,
)
from blue_wren.application.analysis import propose_observations, request_digest_for
from blue_wren.application.analysis_provider import AnalysisProvider
from blue_wren.application.analysis_scope import (
    AnalysisScopeError,
    baseline_digest,
    build_analysis_scope,
)
from blue_wren.application.analysis_store import (
    AnalysisRunConflict,
    AnalysisRunNotFound,
    AnalysisRunRepository,
)
from blue_wren.application.company_store import (
    CompanyConflict,
    CompanyNotFound,
    CompanyRepository,
)
from blue_wren.application.event_review import (
    EventReviewError,
    decide_event_finding,
    materiality,
    start_event_review,
)
from blue_wren.application.evidence import DEFAULT_MAX_BYTES, ingest_evidence
from blue_wren.application.evidence_store import (
    EvidenceVersionConflict,
    EvidenceVersionNotFound,
    EvidenceVersionRepository,
)
from blue_wren.application.exporting import assess_checked_export, build_export_manifest
from blue_wren.application.extraction import extract_text
from blue_wren.application.extraction_store import ExtractionNotFound, ExtractionRepository
from blue_wren.application.replay import replay_event
from blue_wren.application.review_store import (
    EventReviewNotFound,
    EventReviewRepository,
    EventReviewStoreConflict,
    StoredEventReview,
)
from blue_wren.domain.analysis import RunBudget, RunStatus
from blue_wren.domain.company import Company
from blue_wren.domain.evidence import DocumentVersion, EvidenceIntakeError, RightsBasis
from blue_wren.domain.exporting import ExportBlocked
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


def _analysis_runs(request: Request) -> AnalysisRunRepository:
    repository: AnalysisRunRepository = request.app.state.analysis_runs
    return repository


def _analysis_provider(request: Request) -> AnalysisProvider:
    provider: AnalysisProvider = request.app.state.analysis_provider
    return provider


def _analysis_model(request: Request) -> str:
    model: str = request.app.state.analysis_model
    return model


class _SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class _SystemSleeper:
    def sleep(self, seconds: Decimal) -> None:
        time.sleep(float(seconds))


def _companies(request: Request) -> CompanyRepository:
    repository: CompanyRepository = request.app.state.companies
    return repository


def _extractions(request: Request) -> ExtractionRepository:
    repository: ExtractionRepository = request.app.state.extractions
    return repository


@router.post("/analysis-runs", response_model=AnalysisRunResponse)
def create_analysis_run(
    request: AnalysisRunRequest,
    response: Response,
    runs: Annotated[AnalysisRunRepository, Depends(_analysis_runs)],
    provider: Annotated[AnalysisProvider, Depends(_analysis_provider)],
    model_id: Annotated[str, Depends(_analysis_model)],
    companies: Annotated[CompanyRepository, Depends(_companies)],
    evidence: Annotated[EvidenceVersionRepository, Depends(_evidence_versions)],
    extractions: Annotated[ExtractionRepository, Depends(_extractions)],
) -> AnalysisRunResponse:
    budget = RunBudget(
        max_prompt_chars=request.budget.max_prompt_chars,
        max_output_tokens=request.budget.max_output_tokens,
        max_provider_calls=request.budget.max_provider_calls,
        max_tool_calls=request.budget.max_tool_calls,
        max_seconds=request.budget.max_seconds,
    )
    try:
        companies.get(request.company_id)
        versions = [evidence.get(version_id) for version_id in request.source_version_ids]
        records = []
        for version in versions:
            try:
                records.append(extractions.get(version.version_id))
            except ExtractionNotFound:
                continue
        scope = build_analysis_scope(
            event_id=request.event_id,
            company_id=request.company_id,
            cutoff_at=request.cutoff_at,
            versions=versions,
            extractions=records,
            baselines=[_baseline(item) for item in request.baselines],
            units=request.units,
        )
    except (CompanyNotFound, EvidenceVersionNotFound, AnalysisScopeError) as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)
        ) from error

    digest = request_digest_for(scope, model_id=model_id, budget=budget)
    try:
        existing = runs.get_by_idempotency_key(request.idempotency_key)
    except AnalysisRunNotFound:
        existing = None
    if existing is not None:
        if existing.request_digest != digest:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"idempotency key {request.idempotency_key} was used for a different request"
                ),
            )
        return AnalysisRunResponse.model_validate(existing)

    run = propose_observations(
        scope,
        provider=provider,
        model_id=model_id,
        budget=budget,
        idempotency_key=request.idempotency_key,
        clock=_SystemClock(),
        sleeper=_SystemSleeper(),
        nonce=secrets.token_hex(8),
    )
    try:
        stored = runs.create(run)
    except AnalysisRunConflict as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    response.status_code = status.HTTP_201_CREATED
    return AnalysisRunResponse.model_validate(stored)


@router.get("/analysis-runs", response_model=list[AnalysisRunSummaryResponse])
def list_analysis_runs(
    event_id: str,
    runs: Annotated[AnalysisRunRepository, Depends(_analysis_runs)],
) -> list[AnalysisRunSummaryResponse]:
    return [
        AnalysisRunSummaryResponse(
            run_id=run.run_id,
            event_id=run.event_id,
            status=run.status,
            failure=run.failure,
            proposed_count=len(run.proposed),
            rejected_count=len(run.rejected),
            provider_calls=run.usage.provider_calls,
            model_id=run.model_id,
            started_at=run.started_at,
        )
        for run in runs.list_for_event(event_id)
    ]


@router.get("/analysis-runs/{run_id}", response_model=AnalysisRunResponse)
def get_analysis_run(
    run_id: str,
    runs: Annotated[AnalysisRunRepository, Depends(_analysis_runs)],
) -> AnalysisRunResponse:
    try:
        return AnalysisRunResponse.model_validate(runs.get(run_id))
    except AnalysisRunNotFound as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error


@router.post(
    "/analysis-runs/{run_id}/event-review",
    response_model=EventReviewResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_review_from_run(
    run_id: str,
    request: AnalysisReviewRequest,
    runs: Annotated[AnalysisRunRepository, Depends(_analysis_runs)],
    reviews: Annotated[EventReviewRepository, Depends(_event_reviews)],
    evidence: Annotated[EvidenceVersionRepository, Depends(_evidence_versions)],
    extractions: Annotated[ExtractionRepository, Depends(_extractions)],
) -> EventReviewResponse:
    try:
        run = runs.get(run_id)
    except AnalysisRunNotFound as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    if run.status is RunStatus.FAILED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=f"run {run_id} failed: {run.failure}"
        )
    baselines = [_baseline(item) for item in request.baselines]
    if baseline_digest(baselines) != run.baseline_digest:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="baselines do not match the run",
        )
    comparisons = tuple(
        (observation, baseline)
        for observation in run.proposed
        for baseline in baselines
        if baseline.metric == observation.metric
    )
    if not comparisons:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=f"run {run_id} proposed nothing to review"
        )
    replay = replay_event(event_id=run.event_id, company_id=run.company_id, comparisons=comparisons)
    try:
        for finding in replay.findings:
            _require_ingested(evidence, finding.evidence)
        session = start_event_review(replay, created_at=datetime.now(UTC))
    except (EvidenceVersionNotFound, EvidenceIntakeError, EventReviewError) as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)
        ) from error
    try:
        stored = reviews.create(session)
    except EventReviewStoreConflict as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    return _review_response(stored, extractions)


def _baseline(item: BaselineObservationRequest) -> BaselineObservation:
    return BaselineObservation(
        metric=item.metric,
        value=item.value,
        unit=item.unit,
        period=item.period,
        basis=item.basis,
        target=item.target,
    )


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


def _company_response(company: Company, reviews: tuple[StoredEventReview, ...]) -> CompanyResponse:
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
        extractions.put(_extraction_record(version, content))
        stored = repository.put(version)
    except EvidenceIntakeError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)
        ) from error
    except EvidenceVersionConflict as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
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
    companies: Annotated[CompanyRepository, Depends(_companies)],
) -> EventReviewResponse:
    replay = _replay(request)
    try:
        companies.get(request.company_id)
        for finding in replay.findings:
            _require_ingested(evidence, finding.evidence)
    except (CompanyNotFound, EvidenceVersionNotFound, EvidenceIntakeError) as error:
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
            max_materiality=max(
                (
                    value
                    for history in stored.session.findings
                    if (value := materiality(history.current_revision.finding)) is not None
                ),
                default=None,
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


@router.post("/event-reviews/{event_id}/exports", response_model=ExportManifestResponse)
def create_export(
    event_id: str,
    repository: Annotated[EventReviewRepository, Depends(_event_reviews)],
    evidence: Annotated[EvidenceVersionRepository, Depends(_evidence_versions)],
    extractions: Annotated[ExtractionRepository, Depends(_extractions)],
) -> ExportManifestResponse:
    try:
        stored = repository.get(event_id)
    except EventReviewNotFound as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    cited = {
        history.current_revision.finding.evidence.document_version_id
        for history in stored.session.findings
    }
    versions: dict[str, DocumentVersion] = {}
    spans: dict[tuple[str, str], str] = {}
    for version_id in cited:
        try:
            versions[version_id] = evidence.get(version_id)
            record = extractions.get(version_id)
        except (EvidenceVersionNotFound, ExtractionNotFound):
            continue
        spans.update({(version_id, span.locator): span.text for span in record.spans})
    try:
        manifest = build_export_manifest(
            stored,
            generated_at=datetime.now(UTC),
            versions=versions,
            spans=spans,
            citation_resolved=lambda reference: _citation_resolved(extractions, reference),
        )
    except ExportBlocked as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=[
                {"finding_id": blocker.finding_id, "code": blocker.code.value}
                for blocker in error.blockers
            ],
        ) from error
    return ExportManifestResponse.model_validate(manifest)


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
        updated = _apply_decision(repository, event_id, finding_id, request)
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


def _apply_decision(
    repository: EventReviewRepository,
    event_id: str,
    finding_id: str,
    request: ReviewDecisionRequest,
) -> StoredEventReview:
    for _ in range(3):
        stored = repository.get(event_id)
        if not any(
            history.current_revision.finding_id == finding_id
            for history in stored.session.findings
        ):
            raise EventReviewError(f"finding not found: {finding_id}")
        pinned = request.expected_revision
        if pinned is not None and stored.revision != pinned:
            raise EventReviewStoreConflict(
                f"expected revision {pinned}, current revision is {stored.revision}"
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
        try:
            return repository.update(session, expected_revision=stored.revision)
        except EventReviewStoreConflict:
            if pinned is not None:
                raise
    raise EventReviewStoreConflict(f"event review changed concurrently: {event_id}")


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
                materiality=materiality(history.current_revision.finding),
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
        target=item.baseline.target,
    )
    return actual, baseline
