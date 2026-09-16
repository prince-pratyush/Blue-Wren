from blue_wren.application.extraction_store import ExtractionNotFound
from blue_wren.domain.extraction import ExtractionRecord


class InMemoryExtractionRepository:
    def __init__(self) -> None:
        self._records: dict[str, ExtractionRecord] = {}

    def get(self, document_version_id: str) -> ExtractionRecord:
        try:
            return self._records[document_version_id]
        except KeyError as error:
            raise ExtractionNotFound(f"extraction not found: {document_version_id}") from error

    def put(self, record: ExtractionRecord) -> ExtractionRecord:
        self._records[record.document_version_id] = record
        return record
