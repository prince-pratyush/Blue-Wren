import os

from fastapi import FastAPI

from blue_wren import __version__
from blue_wren.api.routes import router
from blue_wren.application.review_store import EventReviewRepository
from blue_wren.infrastructure.memory_review_store import InMemoryEventReviewRepository
from blue_wren.infrastructure.sqlite_review_store import SqliteEventReviewRepository


def create_app(event_reviews: EventReviewRepository | None = None) -> FastAPI:
    app = FastAPI(title="Blue Wren API", version=__version__)
    app.state.event_reviews = event_reviews or _default_repository()
    app.include_router(router, prefix="/v1")
    return app


def _default_repository() -> EventReviewRepository:
    path = os.environ.get("BLUE_WREN_DB")
    if path:
        return SqliteEventReviewRepository(path)
    return InMemoryEventReviewRepository()


app = create_app()
