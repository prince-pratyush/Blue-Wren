from collections.abc import AsyncIterator
from copy import deepcopy
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from blue_wren.api.main import create_app
from blue_wren.infrastructure.memory_evidence_store import InMemoryEvidenceVersionRepository


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def client(
    evidence_versions: InMemoryEvidenceVersionRepository,
) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=create_app(evidence_versions=evidence_versions)),
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


@pytest.mark.anyio
async def test_create_event_review_persists_pending_findings(client: AsyncClient) -> None:
    response = await client.post("/v1/event-reviews", json=PAYLOAD)

    assert response.status_code == 201
    body = response.json()
    assert body["event_id"] == "acme-q2-2026"
    assert body["company_id"] == "ACME-AU"
    assert body["revision"] == 1
    assert len(body["findings"]) == 1
    reviewed = body["findings"][0]
    assert reviewed["finding_id"].startswith("finding-")
    assert reviewed["version"] == 1
    assert reviewed["outcome"] == "pending"
    assert reviewed["finding"]["metric"] == "revenue"
    assert reviewed["finding"]["delta"] == "5.0"
    assert reviewed["finding"]["status"] == "proposed"


@pytest.mark.anyio
async def test_get_event_review_returns_stored_state(client: AsyncClient) -> None:
    created = await client.post("/v1/event-reviews", json=PAYLOAD)

    response = await client.get("/v1/event-reviews/acme-q2-2026")

    assert response.status_code == 200
    assert response.json() == created.json()


@pytest.mark.anyio
async def test_create_event_review_rejects_duplicate_event(client: AsyncClient) -> None:
    await client.post("/v1/event-reviews", json=PAYLOAD)

    response = await client.post("/v1/event-reviews", json=PAYLOAD)

    assert response.status_code == 409
    assert "already exists" in response.json()["detail"]


@pytest.mark.anyio
async def test_create_event_review_rejects_uningested_evidence(client: AsyncClient) -> None:
    payload = deepcopy(PAYLOAD)
    payload["actual"]["evidence"]["document_version_id"] = "acme-q2-results:version-9"

    response = await client.post("/v1/event-reviews", json=payload)

    assert response.status_code == 422
    assert response.json()["detail"] == "evidence version not found: acme-q2-results:version-9"


@pytest.mark.anyio
async def test_create_event_review_rejects_evidence_from_another_document(
    client: AsyncClient,
) -> None:
    payload = deepcopy(PAYLOAD)
    payload["actual"]["evidence"]["document_id"] = "acme-q1-results"

    response = await client.post("/v1/event-reviews", json=payload)

    assert response.status_code == 422
    assert "acme-q1-results" in response.json()["detail"]


@pytest.mark.anyio
async def test_get_unknown_event_review_returns_not_found(client: AsyncClient) -> None:
    response = await client.get("/v1/event-reviews/missing")

    assert response.status_code == 404


@pytest.mark.anyio
async def test_list_event_reviews_is_empty_initially(client: AsyncClient) -> None:
    response = await client.get("/v1/event-reviews")

    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.anyio
async def test_list_event_reviews_returns_ordered_summaries(client: AsyncClient) -> None:
    zeta = deepcopy(PAYLOAD)
    zeta["event_id"] = "zeta-q2-2026"
    zeta["company_id"] = "ZETA-AU"
    await client.post("/v1/event-reviews", json=zeta)
    created = await client.post("/v1/event-reviews", json=PAYLOAD)
    finding_id = created.json()["findings"][0]["finding_id"]
    await client.post(
        f"/v1/event-reviews/acme-q2-2026/findings/{finding_id}/decisions",
        json={
            "expected_revision": 1,
            "expected_version": 1,
            "outcome": "accepted",
            "reviewer_id": "analyst-7",
        },
    )

    response = await client.get("/v1/event-reviews")

    assert response.json() == [
        {
            "event_id": "acme-q2-2026",
            "company_id": "ACME-AU",
            "revision": 2,
            "findings_total": 1,
            "findings_pending": 0,
        },
        {
            "event_id": "zeta-q2-2026",
            "company_id": "ZETA-AU",
            "revision": 1,
            "findings_total": 1,
            "findings_pending": 1,
        },
    ]


@pytest.mark.anyio
async def test_create_event_review_keeps_unresolved_findings_pending(
    client: AsyncClient,
) -> None:
    payload = deepcopy(PAYLOAD)
    payload["baseline"]["basis"] = "underlying"

    response = await client.post("/v1/event-reviews", json=payload)

    assert response.status_code == 201
    reviewed = response.json()["findings"][0]
    assert reviewed["outcome"] == "pending"
    assert reviewed["finding"]["status"] == "unresolved"
    assert reviewed["finding"]["reason"] == "basis_mismatch"
