from blue_wren.application.evidence_store import (
    EvidenceVersionConflict,
    EvidenceVersionNotFound,
)
from blue_wren.domain.evidence import DocumentVersion


class InMemoryEvidenceVersionRepository:
    def __init__(self) -> None:
        self._versions: dict[str, DocumentVersion] = {}

    def get(self, version_id: str) -> DocumentVersion:
        try:
            return self._versions[version_id]
        except KeyError as error:
            raise EvidenceVersionNotFound(f"evidence version not found: {version_id}") from error

    def put(self, version: DocumentVersion) -> DocumentVersion:
        existing = self._versions.get(version.version_id)
        if existing is None:
            self._versions[version.version_id] = version
            return version
        if existing != version:
            raise EvidenceVersionConflict(
                f"evidence version already exists with different metadata: {version.version_id}"
            )
        return existing
