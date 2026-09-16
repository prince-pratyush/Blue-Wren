from datetime import UTC, datetime

import pytest

from blue_wren.domain.evidence import DocumentVersion, RightsBasis
from blue_wren.infrastructure.memory_evidence_store import InMemoryEvidenceVersionRepository

SEEDED_VERSION = DocumentVersion(
    document_id="acme-q2-results",
    version_id="acme-q2-results:version-1",
    content_sha256="a" * 64,
    byte_size=1024,
    media_type="application/pdf",
    source_name="ACME investor relations",
    rights_basis=RightsBasis.PUBLIC,
    published_at=datetime(2026, 8, 20, 8, 0, tzinfo=UTC),
    available_at=datetime(2026, 8, 20, 8, 1, tzinfo=UTC),
    ingested_at=datetime(2026, 8, 20, 9, 0, tzinfo=UTC),
)


@pytest.fixture
def evidence_versions() -> InMemoryEvidenceVersionRepository:
    repository = InMemoryEvidenceVersionRepository()
    repository.put(SEEDED_VERSION)
    return repository
