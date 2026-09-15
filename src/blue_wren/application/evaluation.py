from collections import defaultdict
from fractions import Fraction

from blue_wren.domain.evaluation import EvaluationReport, ExpectedFinding
from blue_wren.domain.findings import Finding


def score_findings(
    *,
    expected: tuple[ExpectedFinding, ...],
    emitted: tuple[Finding, ...],
) -> EvaluationReport:
    remaining_expected = list(expected)
    remaining_emitted = list(emitted)
    true_positives = 0

    for expected_finding in expected:
        match = next(
            (
                finding
                for finding in remaining_emitted
                if not _mismatches(expected_finding, finding)
            ),
            None,
        )
        if match is not None:
            remaining_expected.remove(expected_finding)
            remaining_emitted.remove(match)
            true_positives += 1

    expected_by_metric: dict[str, list[ExpectedFinding]] = defaultdict(list)
    emitted_by_metric: dict[str, list[Finding]] = defaultdict(list)
    for expected_finding in remaining_expected:
        expected_by_metric[expected_finding.metric].append(expected_finding)
    for emitted_finding in remaining_emitted:
        emitted_by_metric[emitted_finding.metric].append(emitted_finding)

    critical_errors = tuple(
        f"{metric}: {field} mismatch"
        for metric, expected_group in expected_by_metric.items()
        for expected_finding, emitted_finding in zip(
            expected_group,
            emitted_by_metric.get(metric, []),
            strict=False,
        )
        for field in _mismatches(expected_finding, emitted_finding)
    )
    false_positives = len(remaining_emitted)
    false_negatives = len(remaining_expected)
    precision = Fraction(true_positives, len(emitted)) if emitted else Fraction(1, 1)
    recall = Fraction(true_positives, len(expected)) if expected else Fraction(1, 1)

    return EvaluationReport(
        passed=false_positives == 0 and false_negatives == 0,
        precision=precision,
        recall=recall,
        true_positives=true_positives,
        false_positives=false_positives,
        false_negatives=false_negatives,
        critical_errors=critical_errors,
    )

def _mismatches(expected: ExpectedFinding, emitted: Finding) -> tuple[str, ...]:
    fields = (
        ("metric", expected.metric == emitted.metric),
        ("actual", expected.actual == emitted.actual),
        ("baseline", expected.baseline == emitted.baseline),
        ("delta", expected.delta == emitted.delta),
        ("unit", expected.unit == emitted.unit),
        ("period", expected.period == emitted.period),
        (
            "evidence document",
            expected.evidence_document_id == emitted.evidence.document_id,
        ),
        (
            "evidence document version",
            expected.evidence_document_version_id == emitted.evidence.document_version_id,
        ),
        ("status", expected.status == emitted.status),
    )
    return tuple(name for name, matches in fields if not matches)
