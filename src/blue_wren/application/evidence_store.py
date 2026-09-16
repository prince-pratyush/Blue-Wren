from typing import Protocol

from blue_wren.domain.evidence import DocumentVersion


class EvidenceVersionNotFound(LookupError):
    pass


class EvidenceVersionConflict(ValueError):
    pass


class EvidenceVersionRepository(Protocol):
    def get(self, version_id: str) -> DocumentVersion: ...

    def put(self, version: DocumentVersion) -> DocumentVersion: ...
