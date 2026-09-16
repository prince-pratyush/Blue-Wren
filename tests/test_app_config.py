from pathlib import Path
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from blue_wren.api.main import create_app
from blue_wren.infrastructure.memory_review_store import InMemoryEventReviewRepository
from blue_wren.infrastructure.sqlite_review_store import SqliteEventReviewRepository

PAYLOAD: dict[str, Any] = {
    "event_id": "acme-q2-2026",
    "company_id": "ACME-AU",
    "actual": {
        "metric": "revenue",
        "value": "125.0",
        "unit": "AUD_millions",
        "period": "2026-Q2",
        "basis": "reported",
        "evidence": {
            "document_id": "acme-q2-results",
            "document_version_id": "acme-q2-results:version-1",
            "locator": "page=2;table=results;row=revenue",
        },
    },
    "baseline": {
        "metric": "revenue",
        "value": "120.0",
        "unit": "AUD_millions",
        "period": "2026-Q2",
        "basis": "reported",
    },
}


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def test_app_defaults_to_memory_store(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BLUE_WREN_DB", raising=False)

    app = create_app()

    assert isinstance(app.state.event_reviews, InMemoryEventReviewRepository)


def test_app_uses_sqlite_store_when_configured(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("BLUE_WREN_DB", str(tmp_path / "reviews.db"))

    app = create_app()

    assert isinstance(app.state.event_reviews, SqliteEventReviewRepository)


@pytest.mark.anyio
async def test_reviews_survive_app_restart_with_sqlite(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("BLUE_WREN_DB", str(tmp_path / "reviews.db"))
    async with AsyncClient(
        transport=ASGITransport(app=create_app()), base_url="http://test"
    ) as first:
        created = await first.post("/v1/event-reviews", json=PAYLOAD)
        assert created.status_code == 201

    async with AsyncClient(
        transport=ASGITransport(app=create_app()), base_url="http://test"
    ) as second:
        response = await second.get("/v1/event-reviews/acme-q2-2026")

    assert response.status_code == 200
    assert response.json() == created.json()
