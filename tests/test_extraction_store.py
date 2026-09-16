from pathlib import Path

import pytest

from blue_wren.application.extraction_store import ExtractionNotFound, ExtractionRepository
from blue_wren.domain.extraction import ExtractionRecord, ExtractionStatus, TextSpan
from blue_wren.infrastructure.memory_extraction_store import InMemoryExtractionRepository
from blue_wren.infrastructure.sqlite_extraction_store import SqliteExtractionRepository

VERSION_ID = "acme-q2-results:version-1"


@pytest.fixture(params=["memory", "sqlite"])
def repository(request: pytest.FixtureRequest, tmp_path: Path) -> ExtractionRepository:
    if request.param == "memory":
        return InMemoryExtractionRepository()
    return SqliteExtractionRepository(tmp_path / "extractions.db")


def _extracted() -> ExtractionRecord:
    return ExtractionRecord(
        document_version_id=VERSION_ID,
        status=ExtractionStatus.EXTRACTED,
        page_count=2,
        spans=(
            TextSpan(VERSION_ID, 1, 1, "Revenue rose to 125.0 million.", "page=1;span=1"),
            TextSpan(VERSION_ID, 2, 1, "EBITDA margin was 24 percent.", "page=2;span=1"),
        ),
    )


def test_put_then_get_returns_extracted_spans(repository: ExtractionRepository) -> None:
    record = _extracted()

    assert repository.put(record) == record
    assert repository.get(VERSION_ID) == record


def test_failed_extraction_keeps_reason_and_no_spans(repository: ExtractionRepository) -> None:
    record = ExtractionRecord(
        document_version_id=VERSION_ID,
        status=ExtractionStatus.FAILED,
        page_count=1,
        spans=(),
        reason="no extractable text",
    )
    repository.put(record)

    stored = repository.get(VERSION_ID)

    assert stored.status is ExtractionStatus.FAILED
    assert stored.reason == "no extractable text"
    assert stored.spans == ()


def test_put_replaces_an_existing_record(repository: ExtractionRepository) -> None:
    repository.put(_extracted())
    unsupported = ExtractionRecord(
        document_version_id=VERSION_ID,
        status=ExtractionStatus.UNSUPPORTED,
        page_count=None,
        spans=(),
        reason="unsupported media type for extraction: application/octet-stream",
    )

    repository.put(unsupported)

    assert repository.get(VERSION_ID) == unsupported


def test_get_unknown_version_raises_not_found(repository: ExtractionRepository) -> None:
    with pytest.raises(ExtractionNotFound, match="missing"):
        repository.get("missing")


def test_sqlite_records_survive_reopen(tmp_path: Path) -> None:
    path = tmp_path / "extractions.db"
    first = SqliteExtractionRepository(path)
    first.put(_extracted())
    first.close()

    assert SqliteExtractionRepository(path).get(VERSION_ID) == _extracted()
