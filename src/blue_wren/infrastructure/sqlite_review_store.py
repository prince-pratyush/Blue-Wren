import json
import sqlite3
from pathlib import Path
from threading import Lock

from blue_wren.application.review_codec import decode_session, encode_session
from blue_wren.application.review_store import (
    EventReviewNotFound,
    EventReviewStoreConflict,
    StoredEventReview,
)
from blue_wren.domain.event_review import EventReviewSession

_SCHEMA = """
CREATE TABLE IF NOT EXISTS event_reviews (
    event_id TEXT PRIMARY KEY,
    revision INTEGER NOT NULL,
    payload TEXT NOT NULL
)
"""


class SqliteEventReviewRepository:
    def __init__(self, path: str | Path) -> None:
        self._connection = sqlite3.connect(str(path), check_same_thread=False)
        self._lock = Lock()
        with self._lock, self._connection:
            self._connection.execute(_SCHEMA)

    def close(self) -> None:
        self._connection.close()

    def get(self, event_id: str) -> StoredEventReview:
        with self._lock:
            row = self._connection.execute(
                "SELECT revision, payload FROM event_reviews WHERE event_id = ?",
                (event_id,),
            ).fetchone()
        if row is None:
            raise EventReviewNotFound(f"event review not found: {event_id}")
        return StoredEventReview(session=decode_session(json.loads(row[1])), revision=row[0])

    def create(self, session: EventReviewSession) -> StoredEventReview:
        payload = json.dumps(encode_session(session))
        try:
            with self._lock, self._connection:
                self._connection.execute(
                    "INSERT INTO event_reviews (event_id, revision, payload) VALUES (?, 1, ?)",
                    (session.event_id, payload),
                )
        except sqlite3.IntegrityError as error:
            raise EventReviewStoreConflict(
                f"event review already exists: {session.event_id}"
            ) from error
        return StoredEventReview(session=session, revision=1)

    def update(
        self, session: EventReviewSession, *, expected_revision: int
    ) -> StoredEventReview:
        payload = json.dumps(encode_session(session))
        with self._lock, self._connection:
            cursor = self._connection.execute(
                "UPDATE event_reviews SET revision = revision + 1, payload = ? "
                "WHERE event_id = ? AND revision = ?",
                (payload, session.event_id, expected_revision),
            )
            if cursor.rowcount == 1:
                return StoredEventReview(session=session, revision=expected_revision + 1)
            row = self._connection.execute(
                "SELECT revision FROM event_reviews WHERE event_id = ?",
                (session.event_id,),
            ).fetchone()
        if row is None:
            raise EventReviewNotFound(f"event review not found: {session.event_id}")
        raise EventReviewStoreConflict(
            f"expected revision {expected_revision}, current revision is {row[0]}"
        )
