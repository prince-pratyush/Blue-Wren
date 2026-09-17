from collections.abc import AsyncIterator
from copy import deepcopy
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from blue_wren.api.main import create_app
from blue_wren.infrastructure.memory_evidence_store import InMemoryEvidenceVersionRepository

ACME = {"company_id": "ACME-AU", "name": "ACME Limited", "exchange": "ASX"}
PAYLOAD: dict[str, Any] = {
    "event_id": "acme-q2-2026",
    "company_id": "ACME-AU",
    "comparisons": [
        {
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
    ],
}


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


@pytest.mark.anyio
async def test_create_company_returns_zero_counts(client: AsyncClient) -> None:
    response = await client.post("/v1/companies", json=ACME)

    assert response.status_code == 201
    assert response.json() == {**ACME, "events_total": 0, "findings_pending": 0}


@pytest.mark.anyio
async def test_create_company_rejects_duplicate(client: AsyncClient) -> None:
    await client.post("/v1/companies", json=ACME)

    response = await client.post("/v1/companies", json=ACME)

    assert response.status_code == 409


@pytest.mark.anyio
async def test_list_companies_counts_events_and_pending_findings(client: AsyncClient) -> None:
    await client.post("/v1/companies", json={**ACME, "company_id": "ZETA-AU", "name": "Zeta"})
    await client.post("/v1/companies", json=ACME)
    await client.post("/v1/event-reviews", json=PAYLOAD)
    second = deepcopy(PAYLOAD)
    second["event_id"] = "acme-q1-2026"
    created = await client.post("/v1/event-reviews", json=second)
    finding_id = created.json()["findings"][0]["finding_id"]
    await client.post(
        f"/v1/event-reviews/acme-q1-2026/findings/{finding_id}/decisions",
        json={
            "expected_revision": 1,
            "expected_version": 1,
            "outcome": "deferred",
            "reviewer_id": "analyst-7",
        },
    )

    response = await client.get("/v1/companies")

    assert response.status_code == 200
    assert response.json() == [
        {**ACME, "events_total": 2, "findings_pending": 1},
        {
            "company_id": "ZETA-AU",
            "name": "Zeta",
            "exchange": "ASX",
            "events_total": 0,
            "findings_pending": 0,
        },
    ]


@pytest.mark.anyio
async def test_create_company_requires_fields(client: AsyncClient) -> None:
    response = await client.post("/v1/companies", json={"company_id": "X"})

    assert response.status_code == 422
