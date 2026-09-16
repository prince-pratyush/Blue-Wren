from blue_wren.application.review_store import (
    EventReviewNotFound,
    EventReviewStoreConflict,
    StoredEventReview,
)
from blue_wren.domain.event_review import EventReviewSession


class InMemoryEventReviewRepository:
    def __init__(self) -> None:
        self._records: dict[str, StoredEventReview] = {}

    def get(self, event_id: str) -> StoredEventReview:
        try:
            return self._records[event_id]
        except KeyError as error:
            raise EventReviewNotFound(f"event review not found: {event_id}") from error

    def list(self) -> tuple[StoredEventReview, ...]:
        return tuple(self._records[event_id] for event_id in sorted(self._records))

    def create(self, session: EventReviewSession) -> StoredEventReview:
        if session.event_id in self._records:
            raise EventReviewStoreConflict(f"event review already exists: {session.event_id}")
        stored = StoredEventReview(session=session, revision=1)
        self._records[session.event_id] = stored
        return stored

    def update(
        self, session: EventReviewSession, *, expected_revision: int
    ) -> StoredEventReview:
        current = self.get(session.event_id)
        if current.revision != expected_revision:
            raise EventReviewStoreConflict(
                f"expected revision {expected_revision}, current revision is {current.revision}"
            )
        stored = StoredEventReview(session=session, revision=current.revision + 1)
        self._records[session.event_id] = stored
        return stored
