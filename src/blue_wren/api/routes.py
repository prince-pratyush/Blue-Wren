from fastapi import APIRouter

from blue_wren.api.schemas import EventReplayRequest, EventReplayResponse
from blue_wren.application.replay import replay_event
from blue_wren.domain.findings import (
    BaselineObservation,
    EvidenceReference,
    ReportedObservation,
)

router = APIRouter()


@router.post("/event-replays", response_model=EventReplayResponse)
def create_event_replay(request: EventReplayRequest) -> EventReplayResponse:
    actual = ReportedObservation(
        metric=request.actual.metric,
        value=request.actual.value,
        unit=request.actual.unit,
        period=request.actual.period,
        evidence=EvidenceReference(
            document_id=request.actual.evidence.document_id,
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
