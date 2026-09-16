import os

from fastapi import FastAPI

from blue_wren import __version__
from blue_wren.api.routes import router
from blue_wren.application.evidence_store import EvidenceVersionRepository
from blue_wren.application.review_store import EventReviewRepository
from blue_wren.infrastructure.memory_evidence_store import InMemoryEvidenceVersionRepository
from blue_wren.infrastructure.memory_review_store import InMemoryEventReviewRepository
from blue_wren.infrastructure.sqlite_evidence_store import SqliteEvidenceVersionRepository
from blue_wren.infrastructure.sqlite_review_store import SqliteEventReviewRepository


def create_app(
    event_reviews: EventReviewRepository | None = None,
    evidence_versions: EvidenceVersionRepository | None = None,
) -> FastAPI:
    app = FastAPI(title="Blue Wren API", version=__version__)
    path = os.environ.get("BLUE_WREN_DB")
    app.state.event_reviews = event_reviews or (
        SqliteEventReviewRepository(path) if path else InMemoryEventReviewRepository()
    )
    app.state.evidence_versions = evidence_versions or (
        SqliteEvidenceVersionRepository(path) if path else InMemoryEvidenceVersionRepository()
    )
    app.include_router(router, prefix="/v1")
    return app


app = create_app()
