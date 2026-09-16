from dataclasses import dataclass
from typing import Protocol

from blue_wren.domain.event_review import EventReviewSession


class EventReviewNotFound(LookupError):
    pass


class EventReviewStoreConflict(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class StoredEventReview:
    session: EventReviewSession
    revision: int


class EventReviewRepository(Protocol):
    def get(self, event_id: str) -> StoredEventReview: ...

    def create(self, session: EventReviewSession) -> StoredEventReview: ...

    def update(
        self, session: EventReviewSession, *, expected_revision: int
    ) -> StoredEventReview: ...
