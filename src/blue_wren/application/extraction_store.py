from typing import Protocol

from blue_wren.domain.extraction import ExtractionRecord


class ExtractionNotFound(LookupError):
    pass


class ExtractionRepository(Protocol):
    def get(self, document_version_id: str) -> ExtractionRecord: ...

    def put(self, record: ExtractionRecord) -> ExtractionRecord: ...
