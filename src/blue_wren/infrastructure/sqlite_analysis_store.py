import json
import sqlite3
from pathlib import Path
from threading import Lock

from blue_wren.application.analysis_codec import decode_run, encode_run
from blue_wren.application.analysis_store import AnalysisRunConflict, AnalysisRunNotFound
from blue_wren.domain.analysis import AnalysisRun

_SCHEMA = """
CREATE TABLE IF NOT EXISTS analysis_runs (
    run_id TEXT PRIMARY KEY,
    event_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    request_digest TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    payload TEXT NOT NULL
)
"""


class SqliteAnalysisRunRepository:
    def __init__(self, path: str | Path) -> None:
        self._connection = sqlite3.connect(str(path), check_same_thread=False)
        self._lock = Lock()
        with self._lock, self._connection:
            self._connection.execute(_SCHEMA)

    def close(self) -> None:
        self._connection.close()

    def get(self, run_id: str) -> AnalysisRun:
        return self._one("run_id", run_id, f"analysis run not found: {run_id}")

    def get_by_idempotency_key(self, idempotency_key: str) -> AnalysisRun:
        return self._one(
            "idempotency_key",
            idempotency_key,
            f"analysis run not found for key: {idempotency_key}",
        )

    def list_for_event(self, event_id: str) -> tuple[AnalysisRun, ...]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT payload FROM analysis_runs WHERE event_id = ? ORDER BY created_at, run_id",
                (event_id,),
            ).fetchall()
        return tuple(decode_run(json.loads(row[0])) for row in rows)

    def create(self, run: AnalysisRun) -> AnalysisRun:
        with self._lock, self._connection:
            row = self._connection.execute(
                "SELECT payload FROM analysis_runs WHERE idempotency_key = ?",
                (run.idempotency_key,),
            ).fetchone()
            if row is None:
                self._connection.execute(
                    "INSERT INTO analysis_runs (run_id, event_id, idempotency_key, request_digest,"
                    " status, created_at, payload) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        run.run_id,
                        run.event_id,
                        run.idempotency_key,
                        run.request_digest,
                        run.status.value,
                        run.started_at.isoformat(),
                        json.dumps(encode_run(run)),
                    ),
                )
                return run
        existing = decode_run(json.loads(row[0]))
        if existing.request_digest != run.request_digest:
            raise AnalysisRunConflict(
                f"idempotency key {run.idempotency_key} was used for a different request"
            )
        return existing

    def _one(self, column: str, value: str, message: str) -> AnalysisRun:
        with self._lock:
            row = self._connection.execute(
                f"SELECT payload FROM analysis_runs WHERE {column} = ?", (value,)
            ).fetchone()
        if row is None:
            raise AnalysisRunNotFound(message)
        return decode_run(json.loads(row[0]))
