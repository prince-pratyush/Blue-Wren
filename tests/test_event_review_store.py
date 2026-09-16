from datetime import UTC, datetime
from pathlib import Path

import pytest

from blue_wren.application.event_review import decide_event_finding, start_event_review
from blue_wren.application.replay import replay_event_fixture
from blue_wren.application.review_store import (
    EventReviewNotFound,
    EventReviewRepository,
    EventReviewStoreConflict,
)
from blue_wren.domain.event_review import EventReviewSession
from blue_wren.domain.review import ReviewOutcome
from blue_wren.infrastructure.memory_review_store import InMemoryEventReviewRepository
from blue_wren.infrastructure.sqlite_review_store import SqliteEventReviewRepository

FIXTURE = Path(__file__).parent / "fixtures" / "acme_q2_2026.json"
NOW = datetime(2026, 9, 16, 1, 0, tzinfo=UTC)


@pytest.fixture(params=["memory", "sqlite"])
def repository(request: pytest.FixtureRequest, tmp_path: Path) -> EventReviewRepository:
    if request.param == "memory":
        return InMemoryEventReviewRepository()
    return SqliteEventReviewRepository(tmp_path / "reviews.db")


def _session() -> EventReviewSession:
    return start_event_review(replay_event_fixture(FIXTURE), created_at=NOW)


def _decide(
    session: EventReviewSession, outcome: ReviewOutcome, reviewer_id: str
) -> EventReviewSession:
    return decide_event_finding(
        session,
        finding_id=session.findings[0].current_revision.finding_id,
        expected_version=1,
        outcome=outcome,
        reviewer_id=reviewer_id,
        decided_at=NOW,
    )


def test_create_then_get_returns_first_revision(repository: EventReviewRepository) -> None:
    session = _session()

    stored = repository.create(session)

    assert stored.revision == 1
    assert stored.session == session
    assert repository.get(session.event_id) == stored


def test_create_rejects_an_existing_event(repository: EventReviewRepository) -> None:
    session = _session()
    repository.create(session)

    with pytest.raises(EventReviewStoreConflict, match="already exists"):
        repository.create(session)


def test_get_unknown_event_raises_not_found(repository: EventReviewRepository) -> None:

    with pytest.raises(EventReviewNotFound, match="missing"):
        repository.get("missing")


def test_update_with_current_revision_persists_decision(repository: EventReviewRepository) -> None:
    session = _session()
    stored = repository.create(session)
    reviewed = _decide(session, ReviewOutcome.ACCEPTED, "analyst-7")

    updated = repository.update(reviewed, expected_revision=stored.revision)

    assert updated.revision == 2
    assert repository.get(session.event_id).session.findings[0].current_outcome is (
        ReviewOutcome.ACCEPTED
    )


def test_update_with_stale_revision_is_rejected_and_keeps_stored_state(
    repository: EventReviewRepository,
) -> None:
    session = _session()
    repository.create(session)
    accepted = _decide(session, ReviewOutcome.ACCEPTED, "analyst-7")
    rejected = _decide(session, ReviewOutcome.REJECTED, "analyst-9")
    repository.update(accepted, expected_revision=1)

    with pytest.raises(EventReviewStoreConflict, match="expected revision 1"):
        repository.update(rejected, expected_revision=1)

    stored = repository.get(session.event_id)
    assert stored.revision == 2
    assert stored.session.findings[0].current_outcome is ReviewOutcome.ACCEPTED


def test_update_unknown_event_raises_not_found(repository: EventReviewRepository) -> None:

    with pytest.raises(EventReviewNotFound):
        repository.update(_session(), expected_revision=1)


def test_sqlite_state_survives_reopen(tmp_path: Path) -> None:
    path = tmp_path / "reviews.db"
    first = SqliteEventReviewRepository(path)
    session = _session()
    first.update(
        _decide(session, ReviewOutcome.DEFERRED, "analyst-7"),
        expected_revision=first.create(session).revision,
    )
    first.close()

    stored = SqliteEventReviewRepository(path).get(session.event_id)

    assert stored.revision == 2
    assert stored.session.findings[0].current_outcome is ReviewOutcome.DEFERRED
