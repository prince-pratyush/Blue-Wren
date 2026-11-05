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
URL = "/v1/event-reviews/acme-q2-2026/exports"


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


async def _cited_review(client: AsyncClient) -> tuple[str, str]:
    uploaded = await client.post(
        "/v1/evidence/versions",
        data={
            "document_id": "acme-q2-results",
            "source_name": "ACME investor relations",
            "rights_basis": "public",
            "published_at": "2026-08-20T08:00:00Z",
            "available_at": "2026-08-20T08:01:00Z",
        },
        files={"file": ("results.txt", b"Revenue was 125.0 million.\n", "text/plain")},
    )
    version_id: str = uploaded.json()["version_id"]
    payload = deepcopy(PAYLOAD)
    evidence = payload["comparisons"][0]["actual"]["evidence"]
    evidence["document_version_id"] = version_id
    evidence["locator"] = "page=1;span=1"
    created = await client.post("/v1/event-reviews", json=payload)
    finding_id: str = created.json()["findings"][0]["finding_id"]
    return version_id, finding_id


@pytest.mark.anyio
async def test_export_is_blocked_while_review_is_pending(client: AsyncClient) -> None:
    version_id, finding_id = await _cited_review(client)

    response = await client.post(URL)

    assert response.status_code == 409
    assert response.json()["detail"] == [{"finding_id": finding_id, "code": "review_pending"}]


@pytest.mark.anyio
async def test_export_manifest_carries_evidence_and_source_hashes(client: AsyncClient) -> None:
    version_id, finding_id = await _cited_review(client)
    await client.post(
        f"/v1/event-reviews/acme-q2-2026/findings/{finding_id}/decisions",
        json={"expected_version": 1, "outcome": "accepted", "reviewer_id": "analyst-7"},
    )

    response = await client.post(URL)

    assert response.status_code == 200
    body = response.json()
    assert body["event_id"] == "acme-q2-2026"
    assert body["revision"] == 2
    finding = body["findings"][0]
    assert finding["finding_id"] == finding_id
    assert finding["delta"] == "5.0"
    assert finding["reviewer_id"] == "analyst-7"
    assert finding["evidence_text"] == "Revenue was 125.0 million."
    assert finding["document_version_id"] == version_id
    source = body["sources"][0]
    assert source["document_version_id"] == version_id
    assert source["content_sha256"] == version_id.split(":")[1]
    assert source["source_name"] == "ACME investor relations"


@pytest.mark.anyio
async def test_export_with_unresolved_citation_is_blocked(client: AsyncClient) -> None:
    created = await client.post("/v1/event-reviews", json=PAYLOAD)
    finding_id = created.json()["findings"][0]["finding_id"]
    await client.post(
        f"/v1/event-reviews/acme-q2-2026/findings/{finding_id}/decisions",
        json={"expected_version": 1, "outcome": "accepted", "reviewer_id": "analyst-7"},
    )

    response = await client.post(URL)

    assert response.status_code == 409
    assert response.json()["detail"] == [{"finding_id": finding_id, "code": "citation_unresolved"}]


@pytest.mark.anyio
async def test_export_for_unknown_event_is_not_found(client: AsyncClient) -> None:
    response = await client.post("/v1/event-reviews/missing/exports")

    assert response.status_code == 404
