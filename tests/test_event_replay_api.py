from collections.abc import AsyncIterator
from copy import deepcopy
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from blue_wren.api.main import create_app


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

PAYLOAD: dict[str, Any] = {
    "event_id": "acme-q2-2026",
    "company_id": "ACME-AU",
    "actual": {
        "metric": "revenue",
        "value": "125.0",
        "unit": "AUD_millions",
        "period": "2026-Q2",
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
    },
}


@pytest.mark.anyio
async def test_event_replay_returns_an_evidence_linked_finding(
    client: AsyncClient,
) -> None:
    response = await client.post("/v1/event-replays", json=PAYLOAD)

    assert response.status_code == 200
    assert response.json() == {
        "event_id": "acme-q2-2026",
        "company_id": "ACME-AU",
        "findings": [
            {
                "metric": "revenue",
                "actual": "125.0",
                "baseline": "120.0",
                "delta": "5.0",
                "unit": "AUD_millions",
                "period": "2026-Q2",
                "evidence": {
                    "document_id": "acme-q2-results",
                    "document_version_id": "acme-q2-results:version-1",
                    "locator": "page=2;table=results;row=revenue",
                },
                "status": "proposed",
                "reason": None,
            }
        ],
    }


@pytest.mark.anyio
async def test_event_replay_exposes_an_unresolved_unit_mismatch(
    client: AsyncClient,
) -> None:
    payload = deepcopy(PAYLOAD)
    payload["baseline"]["unit"] = "AUD_thousands"

    response = await client.post("/v1/event-replays", json=payload)

    assert response.status_code == 200
    finding = response.json()["findings"][0]
    assert finding["status"] == "unresolved"
    assert finding["delta"] is None
    assert finding["reason"] == "unit_mismatch"


@pytest.mark.anyio
async def test_event_replay_rejects_missing_evidence(client: AsyncClient) -> None:
    payload = deepcopy(PAYLOAD)
    del payload["actual"]["evidence"]

    response = await client.post("/v1/event-replays", json=payload)

    assert response.status_code == 422


@pytest.mark.anyio
async def test_event_replay_rejects_missing_evidence_version(client: AsyncClient) -> None:
    payload = deepcopy(PAYLOAD)
    del payload["actual"]["evidence"]["document_version_id"]

    response = await client.post("/v1/event-replays", json=payload)

    assert response.status_code == 422


@pytest.mark.anyio
async def test_event_replay_accepts_content_addressed_version_ids(
    client: AsyncClient,
) -> None:
    payload = deepcopy(PAYLOAD)
    version_id = f"acme-q2-results:{'a' * 64}"
    payload["actual"]["evidence"]["document_version_id"] = version_id

    response = await client.post("/v1/event-replays", json=payload)

    assert response.status_code == 200
    assert response.json()["findings"][0]["evidence"]["document_version_id"] == version_id
