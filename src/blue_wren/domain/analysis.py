from dataclasses import dataclass
from datetime import datetime

from blue_wren.domain.findings import BaselineObservation


@dataclass(frozen=True, slots=True)
class SourceSpan:
    document_id: str
    document_version_id: str
    page: int
    index: int
    locator: str
    text: str


@dataclass(frozen=True, slots=True)
class AnalysisScope:
    event_id: str
    company_id: str
    cutoff_at: datetime
    metrics: tuple[str, ...]
    units: tuple[str, ...]
    spans: tuple[SourceSpan, ...]
    baselines: tuple[BaselineObservation, ...]
