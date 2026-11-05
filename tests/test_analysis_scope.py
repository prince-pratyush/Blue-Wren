from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from blue_wren.application.analysis_scope import (
    AnalysisScopeError,
    baseline_digest,
    build_analysis_scope,
    scope_digest,
)
from blue_wren.domain.evidence import DocumentVersion, RightsBasis
from blue_wren.domain.extraction import ExtractionRecord, ExtractionStatus, TextSpan
from blue_wren.domain.findings import BaselineObservation

CUTOFF = datetime(2026, 8, 20, 0, 0, tzinfo=UTC)
VERSION = DocumentVersion(
    document_id="acme-q2-results",
    version_id="acme-q2-results:v1",
    content_sha256="a" * 64,
    byte_size=10,
    media_type="text/plain",
    source_name="ACME",
    rights_basis=RightsBasis.PUBLIC,
    published_at=CUTOFF - timedelta(hours=2),
    available_at=CUTOFF - timedelta(hours=1),
    ingested_at=CUTOFF - timedelta(minutes=30),
)
SPANS = (
    TextSpan(VERSION.version_id, 2, 1, "EBITDA was 30.0 million.", "page=2;span=1"),
    TextSpan(VERSION.version_id, 1, 2, "Second paragraph.", "page=1;span=2"),
    TextSpan(VERSION.version_id, 1, 1, "Revenue was 125.0 million.", "page=1;span=1"),
)
EXTRACTED = ExtractionRecord(VERSION.version_id, ExtractionStatus.EXTRACTED, 2, SPANS)
BASELINES = (
    BaselineObservation("revenue", Decimal("120.0"), "AUD_millions", "2026-Q2", "reported"),
    BaselineObservation("ebitda", Decimal("32.0"), "AUD_millions", "2026-Q2", "reported"),
    BaselineObservation(
        "revenue", Decimal("122.0"), "AUD_millions", "2026-Q2", "reported", "consensus"
    ),
)


def _scope(**overrides: object):  # type: ignore[no-untyped-def]
    arguments = {
        "event_id": "acme-q2-2026",
        "company_id": "ACME-AU",
        "cutoff_at": CUTOFF,
        "versions": (VERSION,),
        "extractions": (EXTRACTED,),
        "baselines": BASELINES,
    }
    arguments.update(overrides)
    return build_analysis_scope(**arguments)  # type: ignore[arg-type]


def test_scope_derives_metrics_units_and_sorted_spans() -> None:
    scope = _scope(units=("AUD_thousands",))

    assert scope.metrics == ("ebitda", "revenue")
    assert scope.units == ("AUD_millions", "AUD_thousands")
    assert [span.locator for span in scope.spans] == [
        "page=1;span=1",
        "page=1;span=2",
        "page=2;span=1",
    ]
    assert {span.document_id for span in scope.spans} == {"acme-q2-results"}


def test_scope_refuses_a_version_available_after_the_cutoff() -> None:
    late = replace(VERSION, available_at=CUTOFF + timedelta(seconds=1))

    with pytest.raises(AnalysisScopeError, match="available after cutoff"):
        _scope(versions=(late,))


@pytest.mark.parametrize("status", [ExtractionStatus.FAILED, ExtractionStatus.UNSUPPORTED])
def test_scope_refuses_unextracted_versions_by_name(status: ExtractionStatus) -> None:
    record = ExtractionRecord(VERSION.version_id, status, None, (), reason="x")

    with pytest.raises(
        AnalysisScopeError, match=f"acme-q2-results:v1 extraction is {status.value}"
    ):
        _scope(extractions=(record,))


def test_scope_refuses_a_version_without_extraction() -> None:
    with pytest.raises(AnalysisScopeError, match="has no extraction"):
        _scope(extractions=())


def test_scope_refuses_duplicate_versions_and_naive_cutoff() -> None:
    with pytest.raises(AnalysisScopeError, match="duplicate document version"):
        _scope(versions=(VERSION, VERSION))
    with pytest.raises(AnalysisScopeError, match="cutoff_at must include a timezone"):
        _scope(cutoff_at=datetime(2026, 8, 20))


def test_scope_requires_a_baseline() -> None:
    with pytest.raises(AnalysisScopeError, match="at least one baseline"):
        _scope(baselines=())


def test_scope_digest_is_stable_under_reordering_and_sensitive_to_text() -> None:
    reordered = ExtractionRecord(VERSION.version_id, ExtractionStatus.EXTRACTED, 2, SPANS[::-1])
    edited = ExtractionRecord(
        VERSION.version_id,
        ExtractionStatus.EXTRACTED,
        2,
        (replace(SPANS[0], text="EBITDA was 31.0 million."), *SPANS[1:]),
    )

    assert scope_digest(_scope()) == scope_digest(_scope(extractions=(reordered,)))
    assert scope_digest(_scope()) != scope_digest(_scope(extractions=(edited,)))


def test_baseline_digest_changes_with_unit_and_ignores_order() -> None:
    assert baseline_digest(BASELINES) == baseline_digest(BASELINES[::-1])
    changed = (replace(BASELINES[0], unit="AUD_thousands"), *BASELINES[1:])
    assert baseline_digest(BASELINES) != baseline_digest(changed)
