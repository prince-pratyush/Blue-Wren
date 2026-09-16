from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from blue_wren.application.evidence import ingest_evidence
from blue_wren.application.evidence_store import (
    EvidenceVersionConflict,
    EvidenceVersionNotFound,
    EvidenceVersionRepository,
)
from blue_wren.domain.evidence import DocumentVersion, RightsBasis
from blue_wren.infrastructure.memory_evidence_store import InMemoryEvidenceVersionRepository
from blue_wren.infrastructure.sqlite_evidence_store import SqliteEvidenceVersionRepository

PUBLISHED = datetime(2026, 8, 20, 8, 0, tzinfo=UTC)


@pytest.fixture(params=["memory", "sqlite"])
def repository(request: pytest.FixtureRequest, tmp_path: Path) -> EvidenceVersionRepository:
    if request.param == "memory":
        return InMemoryEvidenceVersionRepository()
    return SqliteEvidenceVersionRepository(tmp_path / "evidence.db")


def _version(content: bytes = b"%PDF-1.7\nQuarterly results") -> DocumentVersion:
    return ingest_evidence(
        document_id="acme-q2-results",
        content=content,
        media_type="application/pdf",
        source_name="ACME investor relations",
        rights_basis=RightsBasis.PUBLIC,
        published_at=PUBLISHED,
        available_at=PUBLISHED + timedelta(minutes=1),
        ingested_at=PUBLISHED + timedelta(hours=1),
    )


def test_put_then_get_returns_the_version(repository: EvidenceVersionRepository) -> None:
    version = _version()

    stored = repository.put(version)

    assert stored == version
    assert repository.get(version.version_id) == version


def test_put_is_idempotent_for_identical_versions(
    repository: EvidenceVersionRepository,
) -> None:
    version = _version()
    repository.put(version)

    assert repository.put(version) == version


def test_put_rejects_conflicting_metadata_for_same_version(
    repository: EvidenceVersionRepository,
) -> None:
    version = _version()
    repository.put(version)

    with pytest.raises(EvidenceVersionConflict, match=version.version_id):
        repository.put(replace(version, source_name="Other source"))


def test_get_unknown_version_raises_not_found(repository: EvidenceVersionRepository) -> None:
    with pytest.raises(EvidenceVersionNotFound, match="missing"):
        repository.get("missing")


def test_distinct_content_creates_distinct_versions(
    repository: EvidenceVersionRepository,
) -> None:
    first = repository.put(_version())
    second = repository.put(_version(b"%PDF-1.7\nRestated results"))

    assert first.version_id != second.version_id
    assert repository.get(second.version_id).content_sha256 == second.content_sha256


def test_sqlite_versions_survive_reopen(tmp_path: Path) -> None:
    path = tmp_path / "evidence.db"
    version = _version()
    first = SqliteEvidenceVersionRepository(path)
    first.put(version)
    first.close()

    assert SqliteEvidenceVersionRepository(path).get(version.version_id) == version
