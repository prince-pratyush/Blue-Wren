from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

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


@dataclass(frozen=True, slots=True)
class RunBudget:
    max_prompt_chars: int
    max_output_tokens: int
    max_provider_calls: int
    max_tool_calls: int
    max_seconds: Decimal
