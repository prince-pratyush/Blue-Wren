from fastapi import FastAPI

from blue_wren import __version__
from blue_wren.api.routes import router
from blue_wren.application.review_store import EventReviewRepository
from blue_wren.infrastructure.memory_review_store import InMemoryEventReviewRepository


def create_app(event_reviews: EventReviewRepository | None = None) -> FastAPI:
    app = FastAPI(title="Blue Wren API", version=__version__)
    app.state.event_reviews = event_reviews or InMemoryEventReviewRepository()
    app.include_router(router, prefix="/v1")
    return app


app = create_app()
