from dataclasses import dataclass

from blue_wren.domain.review import FindingHistory


@dataclass(frozen=True, slots=True)
class EventReviewSession:
    event_id: str
    company_id: str
    findings: tuple[FindingHistory, ...]
