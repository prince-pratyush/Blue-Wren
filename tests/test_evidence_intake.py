from datetime import UTC, datetime
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from blue_wren.application.evidence import ingest_evidence
from blue_wren.domain.evidence import EvidenceIntakeError, RightsBasis

PUBLISHED_AT = datetime(2026, 8, 20, 8, 0, tzinfo=UTC)
AVAILABLE_AT = datetime(2026, 8, 20, 8, 1, tzinfo=UTC)
INGESTED_AT = datetime(2026, 9, 15, 5, 0, tzinfo=UTC)
PDF_CONTENT = b"%PDF-1.7\nQuarterly results"


def xlsx_content(*, include_macro: bool = False) -> bytes:
    buffer = BytesIO()
    with ZipFile(buffer, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", "<Types />")
        archive.writestr("xl/workbook.xml", "<workbook />")
        if include_macro:
            archive.writestr("xl/vbaProject.bin", b"macro")
    return buffer.getvalue()


def incomplete_xlsx_content() -> bytes:
    buffer = BytesIO()
    with ZipFile(buffer, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", "<Types />")
    return buffer.getvalue()


def test_ingest_evidence_creates_an_immutable_content_version() -> None:
    version = ingest_evidence(
        document_id="acme-q2-results",
        content=PDF_CONTENT,
        media_type="application/pdf",
        source_name="ACME investor relations",
        rights_basis=RightsBasis.PUBLIC,
        published_at=PUBLISHED_AT,
        available_at=AVAILABLE_AT,
        ingested_at=INGESTED_AT,
    )

    assert version.content_sha256 == (
        "bc42cdfc4c2dccda95c4a2a567e8debe40abc1e1b80ee5e13336711a3dcd337e"
    )
    assert version.version_id == f"acme-q2-results:{version.content_sha256}"
    assert version.byte_size == len(PDF_CONTENT)
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
            content=PDF_CONTENT,
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
            content=PDF_CONTENT,
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
            content=PDF_CONTENT,
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
            content=PDF_CONTENT,
            media_type="application/pdf",
            source_name=" ",
            rights_basis=RightsBasis.PUBLIC,
            published_at=PUBLISHED_AT,
            available_at=AVAILABLE_AT,
            ingested_at=INGESTED_AT,
        )


@pytest.mark.parametrize(
    ("media_type", "content", "message"),
    [
        (
            "application/x-msdownload",
            b"MZ",
            "unsupported media type: application/x-msdownload",
        ),
        (
            "application/pdf",
            b"not a pdf",
            "content does not match declared media type",
        ),
        (
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            b"not a zip package",
            "content does not match declared media type",
        ),
        ("text/plain", b"\xff", "content does not match declared media type"),
        ("text/html", b"not html", "content does not match declared media type"),
        (
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            incomplete_xlsx_content(),
            "content does not match declared media type",
        ),
    ],
)
def test_ingest_evidence_rejects_unsupported_or_disguised_content(
    media_type: str,
    content: bytes,
    message: str,
) -> None:
    with pytest.raises(EvidenceIntakeError, match=message):
        ingest_evidence(
            document_id="acme-q2-results",
            content=content,
            media_type=media_type,
            source_name="ACME investor relations",
            rights_basis=RightsBasis.PUBLIC,
            published_at=PUBLISHED_AT,
            available_at=AVAILABLE_AT,
            ingested_at=INGESTED_AT,
        )


@pytest.mark.parametrize(
    ("media_type", "content"),
    [
        ("application/pdf", b"%PDF-1.7\nQuarterly results"),
        ("text/plain", b"Quarterly results"),
        ("text/html", b"<!doctype html><title>Results</title>"),
        (
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            xlsx_content(),
        ),
    ],
)
def test_ingest_evidence_accepts_supported_media_signatures(
    media_type: str,
    content: bytes,
) -> None:
    version = ingest_evidence(
        document_id="acme-q2-results",
        content=content,
        media_type=media_type,
        source_name="ACME investor relations",
        rights_basis=RightsBasis.PUBLIC,
        published_at=PUBLISHED_AT,
        available_at=AVAILABLE_AT,
        ingested_at=INGESTED_AT,
    )

    assert version.media_type == media_type


def test_ingest_evidence_rejects_macro_enabled_workbook() -> None:
    with pytest.raises(EvidenceIntakeError, match="macro-enabled workbooks are unsupported"):
        ingest_evidence(
            document_id="acme-q2-results",
            content=xlsx_content(include_macro=True),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            source_name="ACME investor relations",
            rights_basis=RightsBasis.PUBLIC,
            published_at=PUBLISHED_AT,
            available_at=AVAILABLE_AT,
            ingested_at=INGESTED_AT,
        )


def test_ingest_evidence_canonicalizes_media_type_parameters() -> None:
    version = ingest_evidence(
        document_id="acme-q2-results",
        content=b"Quarterly results",
        media_type="Text/Plain; charset=utf-8",
        source_name="ACME investor relations",
        rights_basis=RightsBasis.PUBLIC,
        published_at=PUBLISHED_AT,
        available_at=AVAILABLE_AT,
        ingested_at=INGESTED_AT,
    )

    assert version.media_type == "text/plain"
