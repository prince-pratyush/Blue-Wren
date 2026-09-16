import sqlite3
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from threading import Lock

from blue_wren.application.evidence_store import (
    EvidenceVersionConflict,
    EvidenceVersionNotFound,
)
from blue_wren.domain.evidence import DocumentVersion, RightsBasis

_SCHEMA = """
CREATE TABLE IF NOT EXISTS evidence_versions (
    version_id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    byte_size INTEGER NOT NULL,
    media_type TEXT NOT NULL,
    source_name TEXT NOT NULL,
    rights_basis TEXT NOT NULL,
    published_at TEXT NOT NULL,
    available_at TEXT NOT NULL,
    ingested_at TEXT NOT NULL
)
"""
_COLUMNS = (
    "version_id, document_id, content_sha256, byte_size, media_type, "
    "source_name, rights_basis, published_at, available_at, ingested_at"
)


class SqliteEvidenceVersionRepository:
    def __init__(self, path: str | Path) -> None:
        self._connection = sqlite3.connect(str(path), check_same_thread=False)
        self._lock = Lock()
        with self._lock, self._connection:
            self._connection.execute(_SCHEMA)

    def close(self) -> None:
        self._connection.close()

    def get(self, version_id: str) -> DocumentVersion:
        with self._lock:
            row = self._connection.execute(
                f"SELECT {_COLUMNS} FROM evidence_versions WHERE version_id = ?",
                (version_id,),
            ).fetchone()
        if row is None:
            raise EvidenceVersionNotFound(f"evidence version not found: {version_id}")
        return _decode(row)

    def put(self, version: DocumentVersion) -> DocumentVersion:
        with self._lock, self._connection:
            row = self._connection.execute(
                f"SELECT {_COLUMNS} FROM evidence_versions WHERE version_id = ?",
                (version.version_id,),
            ).fetchone()
            if row is None:
                self._connection.execute(
                    f"INSERT INTO evidence_versions ({_COLUMNS}) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    _encode(version),
                )
                return version
        existing = _decode(row)
        if replace(version, ingested_at=existing.ingested_at) != existing:
            raise EvidenceVersionConflict(
                f"evidence version already exists with different metadata: {version.version_id}"
            )
        return existing


def _encode(version: DocumentVersion) -> tuple[str | int, ...]:
    return (
        version.version_id,
        version.document_id,
        version.content_sha256,
        version.byte_size,
        version.media_type,
        version.source_name,
        version.rights_basis.value,
        version.published_at.isoformat(),
        version.available_at.isoformat(),
        version.ingested_at.isoformat(),
    )


def _decode(row: tuple[str | int, ...]) -> DocumentVersion:
    return DocumentVersion(
        version_id=str(row[0]),
        document_id=str(row[1]),
        content_sha256=str(row[2]),
        byte_size=int(row[3]),
        media_type=str(row[4]),
        source_name=str(row[5]),
        rights_basis=RightsBasis(str(row[6])),
        published_at=datetime.fromisoformat(str(row[7])),
        available_at=datetime.fromisoformat(str(row[8])),
        ingested_at=datetime.fromisoformat(str(row[9])),
    )
