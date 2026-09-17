from collections.abc import AsyncIterator
from copy import deepcopy
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from blue_wren.api.main import create_app
from blue_wren.infrastructure.memory_company_store import InMemoryCompanyRepository
from blue_wren.infrastructure.memory_evidence_store import InMemoryEvidenceVersionRepository

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

DECISION: dict[str, Any] = {
    "expected_revision": 1,
    "expected_version": 1,
    "outcome": "accepted",
    "reviewer_id": "analyst-7",
}


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def client(
    evidence_versions: InMemoryEvidenceVersionRepository,
    companies: InMemoryCompanyRepository,
) -> AsyncIterator[AsyncClient]:
    app = create_app(evidence_versions=evidence_versions, companies=companies)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as test_client:
        yield test_client


async def _create(client: AsyncClient, payload: dict[str, Any] = PAYLOAD) -> str:
    response = await client.post("/v1/event-reviews", json=payload)
    assert response.status_code == 201
    finding_id: str = response.json()["findings"][0]["finding_id"]
    return finding_id


def _url(finding_id: str, event_id: str = "acme-q2-2026") -> str:
    return f"/v1/event-reviews/{event_id}/findings/{finding_id}/decisions"


@pytest.mark.anyio
async def test_decision_records_outcome_and_bumps_revision(client: AsyncClient) -> None:
    finding_id = await _create(client)

    response = await client.post(_url(finding_id), json=DECISION)

    assert response.status_code == 200
    body = response.json()
    assert body["revision"] == 2
    assert body["findings"][0]["outcome"] == "accepted"
    assert body["findings"][0]["version"] == 1
    fetched = await client.get("/v1/event-reviews/acme-q2-2026")
    assert fetched.json() == body


@pytest.mark.anyio
async def test_decision_rejects_stale_revision(client: AsyncClient) -> None:
    finding_id = await _create(client)
    await client.post(_url(finding_id), json={**DECISION, "outcome": "deferred"})

    response = await client.post(_url(finding_id), json=DECISION)

    assert response.status_code == 409
    assert "expected revision 1" in response.json()["detail"]


@pytest.mark.anyio
async def test_decision_rejects_already_reviewed_finding(client: AsyncClient) -> None:
    finding_id = await _create(client)
    await client.post(_url(finding_id), json={**DECISION, "outcome": "deferred"})

    response = await client.post(_url(finding_id), json={**DECISION, "expected_revision": 2})

    assert response.status_code == 409
    assert "already reviewed" in response.json()["detail"]


@pytest.mark.anyio
async def test_decision_cannot_accept_unresolved_finding(client: AsyncClient) -> None:
    payload = deepcopy(PAYLOAD)
    payload["comparisons"][0]["baseline"]["basis"] = "underlying"
    finding_id = await _create(client, payload)

    response = await client.post(_url(finding_id), json=DECISION)

    assert response.status_code == 422
    assert response.json()["detail"] == "unresolved finding cannot be accepted"


@pytest.mark.anyio
async def test_decision_rejects_non_decision_outcome(client: AsyncClient) -> None:
    finding_id = await _create(client)

    response = await client.post(_url(finding_id), json={**DECISION, "outcome": "stale"})

    assert response.status_code == 422


@pytest.mark.anyio
async def test_decision_unknown_finding_returns_not_found(client: AsyncClient) -> None:
    await _create(client)

    response = await client.post(_url("finding-missing"), json=DECISION)

    assert response.status_code == 404


@pytest.mark.anyio
async def test_decision_unknown_event_returns_not_found(client: AsyncClient) -> None:
    response = await client.post(_url("finding-x", event_id="missing"), json=DECISION)

    assert response.status_code == 404
