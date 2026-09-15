from decimal import Decimal

from blue_wren.domain.financial_units import FinancialNormalization, convert_financial_value
from blue_wren.domain.findings import (
    BaselineObservation,
    EvidenceReference,
    FindingStatus,
    ReportedObservation,
    compare_observations,
)


def reported(*, value: str, unit: str, basis: str = "reported") -> ReportedObservation:
    return ReportedObservation(
        metric="revenue",
        value=Decimal(value),
        unit=unit,
        period="2026-Q2",
        basis=basis,
        evidence=EvidenceReference(
            document_id="acme-q2-results",
            document_version_id="acme-q2-results:version-1",
            locator="page=2;table=results;row=revenue",
        ),
    )


def baseline(*, value: str, unit: str, basis: str = "reported") -> BaselineObservation:
    return BaselineObservation(
        metric="revenue",
        value=Decimal(value),
        unit=unit,
        period="2026-Q2",
        basis=basis,
    )


def test_convert_financial_value_handles_currency_scales_exactly() -> None:
    converted = convert_financial_value(
        Decimal("120000"),
        source_unit="AUD_thousands",
        target_unit="AUD_millions",
    )

    assert converted == Decimal("120")


def test_convert_financial_value_handles_basis_points() -> None:
    converted = convert_financial_value(
        Decimal("250"),
        source_unit="basis_points",
        target_unit="percentage_points",
    )

    assert converted == Decimal("2.50")


def test_convert_financial_value_rejects_different_currencies() -> None:
    converted = convert_financial_value(
        Decimal("120"),
        source_unit="USD_millions",
        target_unit="AUD_millions",
    )

    assert converted is None


def test_convert_financial_value_preserves_identical_unknown_units() -> None:
    assert (
        convert_financial_value(
            Decimal("120"),
            source_unit="subscribers",
            target_unit="subscribers",
        )
        == Decimal("120")
    )


def test_convert_financial_value_rejects_different_unknown_units() -> None:
    converted = convert_financial_value(
        Decimal("120"),
        source_unit="subscribers",
        target_unit="customers",
    )

    assert converted is None


def test_comparison_normalizes_baseline_into_reported_unit() -> None:
    finding = compare_observations(
        reported(value="125", unit="AUD_millions"),
        baseline(value="120000", unit="AUD_thousands"),
    )

    assert finding.status is FindingStatus.PROPOSED
    assert finding.actual == Decimal("125")
    assert finding.baseline == Decimal("120")
    assert finding.delta == Decimal("5")
    assert finding.unit == "AUD_millions"
    assert finding.baseline_normalization == FinancialNormalization(
        source_value=Decimal("120000"),
        source_unit="AUD_thousands",
        normalized_value=Decimal("120"),
        normalized_unit="AUD_millions",
    )


def test_comparison_omits_normalization_when_units_are_unchanged() -> None:
    finding = compare_observations(
        reported(value="125", unit="AUD_millions"),
        baseline(value="120", unit="AUD_millions"),
    )

    assert finding.baseline_normalization is None


def test_comparison_keeps_incompatible_dimensions_unresolved() -> None:
    finding = compare_observations(
        reported(value="2.5", unit="percentage_points"),
        baseline(value="2.0", unit="AUD_millions"),
    )

    assert finding.status is FindingStatus.UNRESOLVED
    assert finding.reason == "unit_mismatch"
    assert finding.baseline_normalization is None


def test_comparison_keeps_different_accounting_bases_unresolved() -> None:
    finding = compare_observations(
        reported(value="125", unit="AUD_millions", basis="reported"),
        baseline(value="120", unit="AUD_millions", basis="underlying"),
    )

    assert finding.status is FindingStatus.UNRESOLVED
    assert finding.reason == "basis_mismatch"
    assert finding.basis == "reported"
