from collections.abc import AsyncIterator
from copy import deepcopy
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from blue_wren.api.main import create_app

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

URL = "/v1/event-reviews/acme-q2-2026/export-readiness"


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=create_app()),
        base_url="http://test",
    ) as test_client:
        yield test_client


async def _create(client: AsyncClient, payload: dict[str, Any] = PAYLOAD) -> str:
    response = await client.post("/v1/event-reviews", json=payload)
    assert response.status_code == 201
    finding_id: str = response.json()["findings"][0]["finding_id"]
    return finding_id


@pytest.mark.anyio
async def test_pending_review_blocks_export(client: AsyncClient) -> None:
    finding_id = await _create(client)

    response = await client.get(URL)

    assert response.status_code == 200
    assert response.json() == {
        "event_id": "acme-q2-2026",
        "revision": 1,
        "allowed": False,
        "blockers": [{"finding_id": finding_id, "code": "review_pending"}],
    }


@pytest.mark.anyio
async def test_accepted_review_allows_export(client: AsyncClient) -> None:
    finding_id = await _create(client)
    decision = await client.post(
        f"/v1/event-reviews/acme-q2-2026/findings/{finding_id}/decisions",
        json={
            "expected_revision": 1,
            "expected_version": 1,
            "outcome": "accepted",
            "reviewer_id": "analyst-7",
        },
    )
    assert decision.status_code == 200

    response = await client.get(URL)

    assert response.json() == {
        "event_id": "acme-q2-2026",
        "revision": 2,
        "allowed": True,
        "blockers": [],
    }


@pytest.mark.anyio
async def test_unresolved_finding_blocks_export(client: AsyncClient) -> None:
    payload = deepcopy(PAYLOAD)
    payload["baseline"]["period"] = "2026-Q1"
    finding_id = await _create(client, payload)

    response = await client.get(URL)

    assert response.json()["allowed"] is False
    assert response.json()["blockers"] == [{"finding_id": finding_id, "code": "unresolved"}]


@pytest.mark.anyio
async def test_unknown_event_returns_not_found(client: AsyncClient) -> None:
    response = await client.get("/v1/event-reviews/missing/export-readiness")

    assert response.status_code == 404
