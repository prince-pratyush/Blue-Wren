from dataclasses import replace
from decimal import Decimal
from fractions import Fraction

from blue_wren.application.evaluation import score_findings
from blue_wren.domain.evaluation import ExpectedFinding
from blue_wren.domain.findings import EvidenceReference, Finding, FindingStatus

EXPECTED = (
    ExpectedFinding(
        metric="revenue",
        actual=Decimal("125.0"),
        baseline=Decimal("120.0"),
        delta=Decimal("5.0"),
        unit="AUD_millions",
        period="2026-Q2",
        evidence_document_id="acme-q2-results",
        evidence_document_version_id="acme-q2-results:version-1",
        status=FindingStatus.PROPOSED,
    ),
)


def finding(*, delta: Decimal = Decimal("5.0")) -> Finding:
    return Finding(
        metric="revenue",
        actual=Decimal("125.0"),
        baseline=Decimal("120.0"),
        delta=delta,
        unit="AUD_millions",
        period="2026-Q2",
        evidence=EvidenceReference(
            document_id="acme-q2-results",
            document_version_id="acme-q2-results:version-1",
            locator="page=2;table=results;row=revenue",
        ),
        status=FindingStatus.PROPOSED,
    )


def test_score_findings_passes_an_exact_supported_result() -> None:
    report = score_findings(expected=EXPECTED, emitted=(finding(),))

    assert report.passed is True
    assert report.precision == Fraction(1, 1)
    assert report.recall == Fraction(1, 1)
    assert report.true_positives == 1
    assert report.false_positives == 0
    assert report.false_negatives == 0
    assert report.critical_errors == ()


def test_score_findings_counts_a_missing_finding() -> None:
    report = score_findings(expected=EXPECTED, emitted=())

    assert report.passed is False
    assert report.precision == Fraction(1, 1)
    assert report.recall == Fraction(0, 1)
    assert report.false_negatives == 1


def test_score_findings_blocks_a_wrong_financial_value() -> None:
    report = score_findings(expected=EXPECTED, emitted=(finding(delta=Decimal("50.0")),))

    assert report.passed is False
    assert report.precision == Fraction(0, 1)
    assert report.recall == Fraction(0, 1)
    assert report.false_positives == 1
    assert report.false_negatives == 1
    assert report.critical_errors == ("revenue: delta mismatch",)


def test_score_findings_counts_an_unsupported_extra_finding() -> None:
    extra = Finding(
        metric="ebitda",
        actual=Decimal("20.0"),
        baseline=Decimal("18.0"),
        delta=Decimal("2.0"),
        unit="AUD_millions",
        period="2026-Q2",
        evidence=EvidenceReference(
            document_id="acme-q2-results",
            document_version_id="acme-q2-results:version-1",
            locator="page=2;table=results;row=ebitda",
        ),
        status=FindingStatus.PROPOSED,
    )

    report = score_findings(expected=EXPECTED, emitted=(finding(), extra))

    assert report.passed is False
    assert report.precision == Fraction(1, 2)
    assert report.recall == Fraction(1, 1)
    assert report.false_positives == 1


def test_score_findings_blocks_the_wrong_evidence_version() -> None:
    emitted = replace(
        finding(),
        evidence=EvidenceReference(
            document_id="acme-q2-results",
            document_version_id="acme-q2-results:version-2",
            locator="page=2;table=results;row=revenue",
        ),
    )

    report = score_findings(expected=EXPECTED, emitted=(emitted,))

    assert report.passed is False
    assert report.critical_errors == ("revenue: evidence document version mismatch",)
