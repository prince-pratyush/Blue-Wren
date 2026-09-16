import json
import sqlite3
from pathlib import Path
from threading import Lock

from blue_wren.application.extraction_store import ExtractionNotFound
from blue_wren.domain.extraction import ExtractionRecord, ExtractionStatus, TextSpan

_SCHEMA = """
CREATE TABLE IF NOT EXISTS extraction_records (
    document_version_id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    page_count INTEGER,
    reason TEXT,
    spans TEXT NOT NULL
)
"""


class SqliteExtractionRepository:
    def __init__(self, path: str | Path) -> None:
        self._connection = sqlite3.connect(str(path), check_same_thread=False)
        self._lock = Lock()
        with self._lock, self._connection:
            self._connection.execute(_SCHEMA)

    def close(self) -> None:
        self._connection.close()

    def get(self, document_version_id: str) -> ExtractionRecord:
        with self._lock:
            row = self._connection.execute(
                "SELECT status, page_count, reason, spans FROM extraction_records "
                "WHERE document_version_id = ?",
                (document_version_id,),
            ).fetchone()
        if row is None:
            raise ExtractionNotFound(f"extraction not found: {document_version_id}")
        return ExtractionRecord(
            document_version_id=document_version_id,
            status=ExtractionStatus(row[0]),
            page_count=row[1],
            reason=row[2],
            spans=tuple(
                TextSpan(
                    document_version_id=document_version_id,
                    page=item["page"],
                    index=item["index"],
                    text=item["text"],
                    locator=item["locator"],
                )
                for item in json.loads(row[3])
            ),
        )

    def put(self, record: ExtractionRecord) -> ExtractionRecord:
        spans = json.dumps(
            [
                {"page": span.page, "index": span.index, "text": span.text, "locator": span.locator}
                for span in record.spans
            ]
        )
        with self._lock, self._connection:
            self._connection.execute(
                "INSERT OR REPLACE INTO extraction_records "
                "(document_version_id, status, page_count, reason, spans) VALUES (?, ?, ?, ?, ?)",
                (
                    record.document_version_id,
                    record.status.value,
                    record.page_count,
                    record.reason,
                    spans,
                ),
            )
        return record
