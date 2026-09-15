from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction

from blue_wren.domain.findings import FindingStatus


@dataclass(frozen=True, slots=True)
class ExpectedFinding:
    metric: str
    actual: Decimal
    baseline: Decimal
    delta: Decimal | None
    unit: str
    period: str
    evidence_document_id: str
    evidence_document_version_id: str
    status: FindingStatus


@dataclass(frozen=True, slots=True)
class EvaluationReport:
    passed: bool
    precision: Fraction
    recall: Fraction
    true_positives: int
    false_positives: int
    false_negatives: int
    critical_errors: tuple[str, ...]
