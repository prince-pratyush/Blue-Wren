from decimal import Decimal
from pathlib import Path

from blue_wren.application.replay import replay_event_fixture
from blue_wren.domain.findings import FindingStatus

FIXTURE = Path(__file__).parent / "fixtures" / "acme_q2_2026.json"


def test_replay_produces_an_evidence_linked_variance() -> None:
    result = replay_event_fixture(FIXTURE)

    assert result.event_id == "acme-q2-2026"
    assert len(result.findings) == 1

    finding = result.findings[0]
    assert finding.metric == "revenue"
    assert finding.actual == Decimal("125.0")
    assert finding.baseline == Decimal("120.0")
    assert finding.delta == Decimal("5.0")
    assert finding.unit == "AUD_millions"
    assert finding.period == "2026-Q2"
    assert finding.basis == "reported"
    assert finding.status is FindingStatus.PROPOSED
    assert finding.evidence.document_id == "acme-q2-results"
    assert finding.evidence.document_version_id == "acme-q2-results:version-1"
    assert finding.evidence.locator == "page=2;table=results;row=revenue"


def test_replay_marks_different_periods_as_unresolved(tmp_path: Path) -> None:
    fixture = tmp_path / "different-period.json"
    fixture.write_text(
        """
        {
          "event_id": "acme-q2-2026",
          "company_id": "ACME-AU",
          "actual": {
            "metric": "revenue",
            "value": "125.0",
            "unit": "AUD_millions",
            "period": "2026-Q2",
            "basis": "reported",
            "evidence": {
              "document_id": "acme-q2-results",
              "document_version_id": "acme-q2-results:version-1",
              "locator": "page=2;table=results;row=revenue"
            }
          },
          "baseline": {
            "metric": "revenue",
            "value": "120.0",
            "unit": "AUD_millions",
            "period": "2026-Q1",
            "basis": "reported"
          }
        }
        """,
        encoding="utf-8",
    )

    finding = replay_event_fixture(fixture).findings[0]

    assert finding.status is FindingStatus.UNRESOLVED
    assert finding.delta is None
    assert finding.reason == "period_mismatch"


def test_replay_rejects_an_actual_without_evidence(tmp_path: Path) -> None:
    fixture = tmp_path / "missing-evidence.json"
    fixture.write_text(
        """
        {
          "event_id": "acme-q2-2026",
          "company_id": "ACME-AU",
          "actual": {
            "metric": "revenue",
            "value": "125.0",
            "unit": "AUD_millions",
            "period": "2026-Q2",
            "basis": "reported"
          },
          "baseline": {
            "metric": "revenue",
            "value": "120.0",
            "unit": "AUD_millions",
            "period": "2026-Q2"
          }
        }
        """,
        encoding="utf-8",
    )

    try:
        replay_event_fixture(fixture)
    except ValueError as error:
        assert str(error) == "actual evidence is required"
    else:
        raise AssertionError("missing evidence must be rejected")
