from datetime import UTC, datetime

import pytest

from blue_wren.application.evidence import ingest_evidence
from blue_wren.domain.evidence import EvidenceIntakeError, RightsBasis

PUBLISHED_AT = datetime(2026, 8, 20, 8, 0, tzinfo=UTC)
AVAILABLE_AT = datetime(2026, 8, 20, 8, 1, tzinfo=UTC)
INGESTED_AT = datetime(2026, 9, 15, 5, 0, tzinfo=UTC)


def test_ingest_evidence_creates_an_immutable_content_version() -> None:
    version = ingest_evidence(
        document_id="acme-q2-results",
        content=b"Quarterly results",
        media_type="application/pdf",
        source_name="ACME investor relations",
        rights_basis=RightsBasis.PUBLIC,
        published_at=PUBLISHED_AT,
        available_at=AVAILABLE_AT,
        ingested_at=INGESTED_AT,
    )

    assert version.content_sha256 == (
        "1d809cf070cec50893116131be1eaa346edb77851500b9842490818063a7c47c"
    )
    assert version.version_id == f"acme-q2-results:{version.content_sha256}"
    assert version.byte_size == 17
    assert version.rights_basis is RightsBasis.PUBLIC
    assert version.published_at == PUBLISHED_AT
    assert version.available_at == AVAILABLE_AT
    assert version.ingested_at == INGESTED_AT


@pytest.mark.parametrize(
    ("content", "max_bytes", "message"),
    [
        (b"", 25_000_000, "document is empty"),
        (b"too large", 4, "document exceeds 4 bytes"),
    ],
)
def test_ingest_evidence_rejects_invalid_content(
    content: bytes,
    max_bytes: int,
    message: str,
) -> None:
    with pytest.raises(EvidenceIntakeError, match=message):
        ingest_evidence(
            document_id="acme-q2-results",
            content=content,
            media_type="application/pdf",
            source_name="ACME investor relations",
            rights_basis=RightsBasis.PUBLIC,
            published_at=PUBLISHED_AT,
            available_at=AVAILABLE_AT,
            ingested_at=INGESTED_AT,
            max_bytes=max_bytes,
        )


def test_ingest_evidence_rejects_a_naive_timestamp() -> None:
    with pytest.raises(EvidenceIntakeError, match="published_at must include a timezone"):
        ingest_evidence(
            document_id="acme-q2-results",
            content=b"Quarterly results",
            media_type="application/pdf",
            source_name="ACME investor relations",
            rights_basis=RightsBasis.PUBLIC,
            published_at=datetime(2026, 8, 20, 8, 0),
            available_at=AVAILABLE_AT,
            ingested_at=INGESTED_AT,
        )


def test_ingest_evidence_rejects_impossible_event_order() -> None:
    with pytest.raises(EvidenceIntakeError, match="available_at precedes published_at"):
        ingest_evidence(
            document_id="acme-q2-results",
            content=b"Quarterly results",
            media_type="application/pdf",
            source_name="ACME investor relations",
            rights_basis=RightsBasis.PUBLIC,
            published_at=AVAILABLE_AT,
            available_at=PUBLISHED_AT,
            ingested_at=INGESTED_AT,
        )


def test_ingest_evidence_rejects_ingestion_before_availability() -> None:
    with pytest.raises(EvidenceIntakeError, match="ingested_at precedes available_at"):
        ingest_evidence(
            document_id="acme-q2-results",
            content=b"Quarterly results",
            media_type="application/pdf",
            source_name="ACME investor relations",
            rights_basis=RightsBasis.PUBLIC,
            published_at=PUBLISHED_AT,
            available_at=AVAILABLE_AT,
            ingested_at=PUBLISHED_AT,
        )


def test_ingest_evidence_rejects_empty_source_metadata() -> None:
    with pytest.raises(EvidenceIntakeError, match="source_name is required"):
        ingest_evidence(
            document_id="acme-q2-results",
            content=b"Quarterly results",
            media_type="application/pdf",
            source_name=" ",
            rights_basis=RightsBasis.PUBLIC,
            published_at=PUBLISHED_AT,
            available_at=AVAILABLE_AT,
            ingested_at=INGESTED_AT,
        )
